from mnemo_mcp.relay_schema import RELAY_SCHEMA


def test_has_model_chain_tasks():
    tasks = {
        f.get("task") for f in RELAY_SCHEMA["fields"] if f.get("type") == "model-chain"
    }
    assert tasks == {"embedding", "rerank", "chat"}


def test_key_fields_are_derived():
    derived = {f["key"] for f in RELAY_SCHEMA["fields"] if f.get("derived")}
    assert "GEMINI_API_KEY" in derived and "JINA_AI_API_KEY" in derived


def test_no_hardcoded_priority_strings():
    for cap in RELAY_SCHEMA.get("capabilityInfo", []):
        assert ">" not in cap.get("priority", "")


def test_suggested_models_carry_provider_prefix():
    # Every suggested model except bare-openai must carry a "<provider>/" prefix
    # so the widget derive-keys maps it to the correct key field.
    for f in RELAY_SCHEMA["fields"]:
        if f.get("type") == "model-chain":
            for m in f["suggestedModels"]:
                assert "/" in m, f"suggested model {m!r} lacks a provider prefix"


def test_vertex_express_key_field_present_and_derived():
    # Selecting a vertex_express/gemini model must surface a credential box, so
    # the schema declares GOOGLE_VERTEX_EXPRESS_API_KEY as a derived field. The
    # credential-state layer also recognizes it (see test_credential_state).
    by_key = {f["key"]: f for f in RELAY_SCHEMA["fields"]}
    assert "GOOGLE_VERTEX_EXPRESS_API_KEY" in by_key
    assert by_key["GOOGLE_VERTEX_EXPRESS_API_KEY"].get("derived") is True
    assert "VERTEX_AI_API_KEY" not in by_key  # no dead-end field


API_BASE_KEYS = ("EMBEDDING_API_BASE", "RERANK_API_BASE", "LLM_API_BASE")


def test_api_base_fields_present_as_url():
    by_key = {f["key"]: f for f in RELAY_SCHEMA["fields"]}
    for key in API_BASE_KEYS:
        assert key in by_key, f"{key} missing from relay schema"
        assert by_key[key]["type"] == "url"
        assert by_key[key]["required"] is False


def test_api_base_fields_not_derived():
    # api_base fields must stay always-visible: the renderer only reveals a
    # ``derived`` field when a model chip derives that exact provider ENV key
    # (data-provider-key match). No model derives *_API_BASE, so a derived
    # api_base field would be hidden forever. required:false already carries
    # the "Optional" badge, so visibility costs nothing.
    by_key = {f["key"]: f for f in RELAY_SCHEMA["fields"]}
    for key in API_BASE_KEYS:
        assert not by_key[key].get("derived"), (
            f"{key} must not be derived (would hide it)"
        )


def test_api_base_help_documents_cohere_gateway_path():
    by_key = {f["key"]: f for f in RELAY_SCHEMA["fields"]}
    assert "cohere/v2/embed" in by_key["EMBEDDING_API_BASE"]["helpText"]
    assert "cohere" in by_key["RERANK_API_BASE"]["helpText"]
