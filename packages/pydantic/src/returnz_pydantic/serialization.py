"""Tagged-envelope Pydantic serialization for returnz Result / Maybe.

Use ``RzResult[T, E]`` / ``RzMaybe[T]`` as Pydantic field types (they are
``Annotated`` aliases carrying the schema). Keep using plain ``Result[T, E]`` /
``Maybe[T]`` everywhere else — the ``returnz`` core stays Pydantic-free.

Each variant serializes as a single-key **tagged envelope** and is reconstructed
by that tag — never by class identity, which a serialization boundary strips
(structured clone, RPC, JSON). The tag also keeps ``Some(None)``
(``{"some": null}``) distinct from ``Nothing`` (``{"nothing": true}``). A field
accepts either an already-built variant instance or its dict form.
"""

from collections.abc import Hashable
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from returnz import BatchResult, Err, Maybe, Nothing, Ok, Result, Some


def _type_label(tp: Any) -> str:
    """Short readable name for a type, safe as an OpenAPI component-name part."""
    if get_origin(tp) is Union:
        return "_or_".join(_type_label(arg) for arg in get_args(tp))
    if args := get_args(tp):
        origin = get_origin(tp)
        return "_".join([_type_label(origin), *(_type_label(arg) for arg in args)])
    return tp.__name__ if isinstance(tp, type) else str(tp)


def _qualified(tp: Any) -> str:
    """Fully-qualified identity for a type — distinguishes same-named types."""
    if args := get_args(tp):
        origin = get_origin(tp)
        inner = ",".join(_qualified(arg) for arg in args)
        return f"{_qualified(origin)}[{inner}]"
    if isinstance(tp, type):
        return f"{tp.__module__}.{tp.__qualname__}"
    return str(tp)


def _batch_result_ref(key_type: Any, value_type: Any, error_type: Any) -> str:
    """Core-schema ref yielding a clean, deterministic ``$defs`` key.

    Pydantic strips the ``:id`` suffix and module prefix, leaving e.g.
    ``BatchResult_str_str_DeleteError``; the fully-qualified args in the id
    disambiguate same-named types (module-qualified fallback on collision).
    The id must avoid ``[``, ``]``, ``,`` — pydantic splits on those first.
    Useless behind a ``type`` alias: pydantic overwrites that ref with an
    alias-derived one.
    """
    args = (key_type, value_type, error_type)
    label = "_".join(["BatchResult", *(_type_label(arg) for arg in args)])
    identity = "+".join(_qualified(arg) for arg in args)
    identity = identity.replace("[", "(").replace("]", ")").replace(",", "+")
    return f"returnz.{label}:{identity}"


def _envelope(tag: str, cls: type, value_attr: str | None, value_schema: CoreSchema) -> CoreSchema:
    dict_schema = core_schema.typed_dict_schema({tag: core_schema.typed_dict_field(value_schema)})

    def construct(data: dict[str, Any]) -> Any:
        return cls(data[tag]) if value_attr is not None else cls()

    def to_dict(instance: Any) -> dict[str, Any]:
        return {tag: getattr(instance, value_attr)} if value_attr is not None else {tag: True}

    return core_schema.union_schema(
        [
            core_schema.is_instance_schema(cls),
            core_schema.no_info_after_validator_function(construct, dict_schema),
        ],
        serialization=core_schema.plain_serializer_function_ser_schema(
            to_dict, return_schema=dict_schema
        ),
    )


class _ResultSchema:
    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        value_type, error_type = get_args(source)
        return core_schema.union_schema(
            [
                _envelope("ok", Ok, "value", handler.generate_schema(value_type)),
                _envelope("err", Err, "error", handler.generate_schema(error_type)),
            ]
        )


class _MaybeSchema:
    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        (value_type,) = get_args(source)
        return core_schema.union_schema(
            [
                _envelope("some", Some, "value", handler.generate_schema(value_type)),
                _envelope("nothing", Nothing, None, core_schema.bool_schema()),
            ]
        )


class BatchResultSchema:
    """Marker for a ``BatchResult`` envelope built from runtime type args.

    Unlike the ``RzBatchResult`` alias, ``Annotated[BatchResult[k, v, e],
    BatchResultSchema()]`` keeps the clean component name (``BatchResult_k_v_e``)
    — no alias wrapper overwrites the ref. Used by ``returnz_fastapi.BatchRoute``;
    prefer ``RzBatchResult`` for statically-written fields.
    """

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        key_type, value_type, error_type = get_args(source)
        # dict[key_type, value_type] builds a type from runtime type args (from
        # get_args) — valid at runtime, but mypy can't verify variables-as-types.
        succeeded_type = dict[key_type, value_type]  # type: ignore[valid-type]
        failed_type = dict[key_type, error_type]  # type: ignore[valid-type]
        envelope = core_schema.typed_dict_schema(
            {
                "succeeded": core_schema.typed_dict_field(handler.generate_schema(succeeded_type)),
                "failed": core_schema.typed_dict_field(handler.generate_schema(failed_type)),
            }
        )

        def construct(data: dict[str, Any]) -> Any:
            return BatchResult(succeeded=data["succeeded"], failed=data["failed"])

        def to_dict(instance: Any) -> dict[str, Any]:
            return {"succeeded": instance.succeeded, "failed": instance.failed}

        return core_schema.union_schema(
            [
                core_schema.is_instance_schema(BatchResult),
                core_schema.no_info_after_validator_function(construct, envelope),
            ],
            serialization=core_schema.plain_serializer_function_ser_schema(
                to_dict, return_schema=envelope
            ),
            ref=_batch_result_ref(key_type, value_type, error_type),
        )


type RzResult[T, E] = Annotated[Result[T, E], _ResultSchema()]
type RzMaybe[T] = Annotated[Maybe[T], _MaybeSchema()]
type RzBatchResult[K: Hashable, T, E] = Annotated[BatchResult[K, T, E], BatchResultSchema()]
