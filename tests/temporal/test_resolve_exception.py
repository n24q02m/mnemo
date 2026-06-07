from unittest.mock import MagicMock, patch

from mnemo_mcp.temporal.resolve import find_similar_entity, insert_entity_with_embedding


def test_find_similar_entity_exception_handling():
    conn = MagicMock()
    # Force _vec_table_exists to True so it proceeds to KNN
    with (
        patch("mnemo_mcp.temporal.resolve._vec_table_exists", return_value=True),
        patch("mnemo_mcp.temporal.resolve.logger") as mock_logger,
    ):

        def side_effect(query, *args):
            if "memory_entities_vec" in query:
                raise Exception("KNN error")
            mock_res = MagicMock()
            mock_res.fetchone.return_value = None
            return mock_res

        conn.execute.side_effect = side_effect

        res = find_similar_entity(conn, "name", "type", [0.1] * 768)

        assert res is None
        mock_logger.debug.assert_called_with(
            "temporal.resolve: vec KNN failed (non-blocking): KNN error"
        )


def test_insert_entity_with_embedding_exception_handling():
    conn = MagicMock()
    # Force _vec_table_exists to True
    with (
        patch("mnemo_mcp.temporal.resolve._vec_table_exists", return_value=True),
        patch("mnemo_mcp.temporal.resolve.logger") as mock_logger,
    ):

        def side_effect(query, *args):
            if "INSERT INTO memory_entities_vec" in query:
                raise Exception("Insert error")
            mock_res = MagicMock()
            if "SELECT id FROM memory_entities" in query:
                mock_res.fetchone.return_value = ["some-id"]
            elif "SELECT rowid FROM memory_entities" in query:
                mock_res.fetchone.return_value = [123]
            return mock_res

        conn.execute.side_effect = side_effect

        res = insert_entity_with_embedding(conn, "name", "type", [0.1] * 768)

        assert res == "some-id"
        mock_logger.debug.assert_called_with(
            "temporal.resolve: embedding insert failed (non-blocking): Insert error"
        )
