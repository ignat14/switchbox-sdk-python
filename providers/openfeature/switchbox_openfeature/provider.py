"""OpenFeature provider for Switchbox.

A pure translation layer over the ``switchbox-flags`` client. It contains zero
evaluation logic: every resolve is a direct, in-process call onto the client,
which evaluates rules locally against the CDN config it polls. Nothing about
the architecture changes.

Unlike the web provider (which must pre-evaluate because the OpenFeature web
SDK resolves synchronously), the Python provider needs no caching layer at
all: Switchbox evaluation is already synchronous and local, so each resolve
reads the freshest polled config.

Usage::

    from openfeature import api
    from switchbox_openfeature import SwitchboxProvider

    api.set_provider(SwitchboxProvider(sdk_key="your-sdk-key"))
    client = api.get_client()

    context = EvaluationContext(targeting_key="user-42", attributes={"plan": "pro"})
    client.get_boolean_value("new_checkout", False, context)
"""

from __future__ import annotations

from typing import Any, Callable

from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import FlagNotFoundError, ProviderNotReadyError, TypeMismatchError
from openfeature.flag_evaluation import FlagResolutionDetails, Reason
from openfeature.hook import Hook
from openfeature.provider import AbstractProvider, Metadata

from switchbox import Switchbox

# Sentinel default for get_value: distinguishes "flag missing" (FLAG_NOT_FOUND)
# from a flag that legitimately resolves to None.
_MISSING = object()


def to_user_context(context: EvaluationContext | None) -> dict[str, Any] | None:
    """OpenFeature context -> Switchbox user context.

    ``targeting_key`` becomes ``user_id`` (the rollout-bucketing identity);
    every other attribute passes through as a targeting attribute. An empty
    context maps to no user at all. ``targeting_key`` is authoritative per the
    OpenFeature spec: it wins over an attribute literally named ``user_id``,
    so bucketing can't silently key off a stray attribute.
    """
    if context is None:
        return None
    user: dict[str, Any] = dict(context.attributes or {})
    if context.targeting_key is not None:
        user["user_id"] = context.targeting_key
    return user or None


class SwitchboxProvider(AbstractProvider):
    """OpenFeature provider wrapping the Switchbox client.

    Pass Switchbox constructor options to let the provider own the client
    lifecycle (created on construction, closed on ``shutdown()``)::

        SwitchboxProvider(sdk_key="your-sdk-key")

    Or pass an existing client to share one you already manage (the provider
    will not close it)::

        SwitchboxProvider(client=my_switchbox)
    """

    def __init__(self, client: Switchbox | None = None, **options: Any) -> None:
        if client is not None and options:
            raise ValueError("pass either client=... or Switchbox options, not both")
        if client is None and "sdk_key" not in options:
            raise ValueError("pass sdk_key=... or an existing client=...")
        self._owns_client = client is None
        self._client = client if client is not None else Switchbox(**options)

    def get_metadata(self) -> Metadata:
        return Metadata(name="switchbox")

    def get_provider_hooks(self) -> list[Hook]:
        return []

    def initialize(self, evaluation_context: EvaluationContext) -> None:
        # The client constructor already performed the (blocking) first fetch
        # when we own it; fetch failures surface via on_error, never by
        # raising. Raising here puts the provider in ERROR state so OpenFeature
        # serves code defaults — the same fail-safe posture as the SDKs' own
        # never-throw evaluation (ADR-043). A caller-managed client is left
        # alone: its readiness is the caller's concern.
        if self._owns_client and not self._client.ready:
            raise ProviderNotReadyError("Switchbox config could not be fetched")

    def shutdown(self) -> None:
        if self._owns_client:
            self._client.close()

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[bool]:
        return self._resolve(flag_key, evaluation_context, "boolean", lambda v: isinstance(v, bool))

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[str]:
        return self._resolve(flag_key, evaluation_context, "string", lambda v: isinstance(v, str))

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[int]:
        return self._resolve(
            flag_key,
            evaluation_context,
            "integer",
            lambda v: isinstance(v, int) and not isinstance(v, bool),
        )

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[float]:
        details = self._resolve(
            flag_key,
            evaluation_context,
            "number",
            lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        )
        details.value = float(details.value)
        return details

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Any,
        evaluation_context: EvaluationContext | None = None,
    ) -> FlagResolutionDetails[Any]:
        return self._resolve(
            flag_key, evaluation_context, "object", lambda v: isinstance(v, (dict, list))
        )

    def _resolve(
        self,
        flag_key: str,
        evaluation_context: EvaluationContext | None,
        type_name: str,
        matches: Callable[[Any], bool],
    ) -> FlagResolutionDetails[Any]:
        """Shared tail: evaluate locally, then map absence/type onto OpenFeature errors.

        Raised errors are caught by the OpenFeature SDK, which returns the
        code default with the error code attached — we never guess a value.
        """
        user = to_user_context(evaluation_context)
        value = self._client.get_value(flag_key, user, default=_MISSING)
        if value is _MISSING:
            raise FlagNotFoundError(f"flag '{flag_key}' was not found")
        if not matches(value):
            raise TypeMismatchError(
                f"flag '{flag_key}' resolved to {type(value).__name__}, not {type_name}"
            )
        # CACHED: resolved locally from the cached CDN config — the closest
        # standard reason to what actually happened (no network per evaluation).
        return FlagResolutionDetails(value=value, reason=Reason.CACHED)
