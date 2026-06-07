from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mnemo_mcp.sync.gdrive import _find_file_in_folder, _find_or_create_folder


@pytest.mark.asyncio
async def test_find_file_in_folder_injection():
    token = {"access_token": "test"}
    folder_id = "folder123"
    file_name = "o'malley.db"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"files": []}

    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_request:
        await _find_file_in_folder(token, folder_id, file_name)

        call_args = mock_request.call_args
        params = call_args.kwargs.get("params", {})
        query = params.get("q", "")

        # We expect it to be escaped: name='o\'malley.db'
        assert "name='o\\'malley.db'" in query


@pytest.mark.asyncio
async def test_find_or_create_folder_injection():
    token = {"access_token": "test"}
    folder_name = "folder'name"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"files": []}

    with patch(
        "mnemo_mcp.sync.gdrive._drive_request",
        new_callable=AsyncMock,
        return_value=mock_response,
    ) as mock_request:
        # Avoid the cache and persistence
        with (
            patch("mnemo_mcp.sync.gdrive._folder_id_cache", {}),
            patch("mnemo_mcp.sync.gdrive._load_folder_id", return_value=None),
        ):
            await _find_or_create_folder(token, folder_name)

            # Find the GET call to /files
            found_query = None
            for call in mock_request.call_args_list:
                if call.args[0] == "GET" and "/files" in call.args[1]:
                    found_query = call.kwargs.get("params", {}).get("q", "")
                    break

            assert found_query is not None
            assert "name='folder\\'name'" in found_query
