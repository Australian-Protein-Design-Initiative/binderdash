"""MCP server: authentication, mounting, and the tool surface.

Drives the mounted sub-app in-process over httpx.ASGITransport, so requests pass
through the real middleware stack (CORS, sessions, CSRF) without opening a socket.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from backend.api_keys import generate_key
from backend.persistence.sqlite_repo import SqliteDesignsRepository

MCP_URL = "http://test/api/mcp/"


@pytest.fixture
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A database URL plus a live API key, with the app pointed at it."""
    import backend.api_keys as api_keys_mod
    import backend.auth as auth_mod
    import backend.main as main_mod
    import backend.settings as settings_mod

    url = f"sqlite:///{tmp_path}/mcp.sqlite"
    repo = SqliteDesignsRepository(url)
    repo.init_schema()
    user = repo.upsert_login_identity(provider="local", identifier="alice")
    assert user is not None
    token, key_hash, key_prefix = generate_key()
    key = repo.create_api_key(
        user_id=int(user["id"]), name="mcp", key_hash=key_hash, key_prefix=key_prefix
    )

    patched = settings_mod.settings.model_copy(update={"auth_disabled": False})
    for mod in (settings_mod, main_mod, auth_mod):
        monkeypatch.setattr(mod, "settings", patched)
    # lifespan prefers raw_settings.database over default_sqlite_url; clear it so the
    # test DB is used even when the developer's .env sets DATABASE.
    patched_raw = settings_mod.raw_settings.model_copy(update={"database": ""})
    monkeypatch.setattr(main_mod, "raw_settings", patched_raw)
    monkeypatch.setattr(settings_mod, "raw_settings", patched_raw)
    # main.app is a module-level singleton; without this its lifespan would initialise
    # the real database (see test_api_key_auth.py, which does the same).
    monkeypatch.setattr(main_mod, "default_sqlite_url", lambda: url)
    api_keys_mod.reset_cache()

    yield {"url": url, "token": token, "repo": repo, "key_id": int(key["id"])}
    api_keys_mod.reset_cache()


@pytest_asyncio.fixture
async def app(seeded):
    import backend.main as main_mod

    application = main_mod.app
    application.dependency_overrides.clear()
    started, stop = asyncio.Event(), asyncio.Event()

    # The streamable-HTTP session manager opens anyio cancel scopes, which must be
    # exited by the task that entered them. pytest-asyncio runs async-fixture setup and
    # teardown on *different* tasks, so entering the lifespan inline makes the suite
    # error at teardown, attributed to the wrong test.
    async def run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            started.set()
            await stop.wait()

    task = asyncio.create_task(run_lifespan())
    await started.wait()
    yield application
    stop.set()
    await task


def http_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def mcp_client(app, token: str | None, header: str = "Authorization") -> Client:
    def factory(headers=None, timeout=None, auth=None, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers=headers,
            timeout=timeout,
            auth=auth,
            **kwargs,
        )

    headers = {}
    if token is not None:
        headers[header] = f"Bearer {token}" if header == "Authorization" else token
    return Client(
        StreamableHttpTransport(url=MCP_URL, headers=headers, httpx_client_factory=factory)
    )


class TestAuth:
    async def test_missing_key_is_401_not_a_csrf_403(self, app):
        """The regression test for the CSRF exemption.

        Without it the middleware answers first with text/plain "CSRF token missing",
        which no MCP client can interpret as an auth failure.
        """
        async with http_client(app) as http:
            resp = await http.post(
                "/api/mcp/",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Accept": "application/json, text/event-stream"},
            )
        assert resp.status_code == 401
        assert "CSRF" not in resp.text
        assert "www-authenticate" in {k.lower() for k in resp.headers}

    async def test_slashless_path_redirects_rather_than_404(self, app):
        async with http_client(app) as http:
            resp = await http.post("/api/mcp", json={}, follow_redirects=False)
        assert resp.status_code == 307

    async def test_valid_key_lists_tools(self, app, seeded):
        async with mcp_client(app, seeded["token"]) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert {
            "list_runs",
            "describe_methods",
            "describe_columns",
            "merge_design_columns",
        } <= names

    async def test_binderdash_header_is_accepted(self, app, seeded):
        async with mcp_client(app, seeded["token"], header="X-Binderdash-Api-Key") as client:
            assert await client.list_tools()

    async def test_wrong_key_rejected(self, app):
        with pytest.raises(Exception):
            async with mcp_client(app, "bd_definitely-not-a-key") as client:
                await client.list_tools()

    async def test_revoked_key_rejected_immediately(self, app, seeded):
        """MCP and REST share one key cache, so revocation takes effect at once."""
        async with mcp_client(app, seeded["token"]) as client:
            assert await client.list_tools()

        seeded["repo"].revoke_api_key(seeded["key_id"])
        import backend.api_keys as api_keys_mod

        api_keys_mod.reset_cache()

        with pytest.raises(Exception):
            async with mcp_client(app, seeded["token"]) as client:
                await client.list_tools()


class TestStatusAdvertisesMcp:
    async def test_status_reports_mcp_so_the_ui_can_offer_client_setup(self, app):
        """The account UI shows MCP client config only when this says enabled.

        Without it the "New API key created" panel would hand out setup
        instructions for an endpoint a deployment without the extra never serves.
        """
        async with http_client(app) as http:
            resp = await http.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["mcp"] == {"enabled": True, "path": "/api/mcp/"}


class TestOptionalExtra:
    def test_without_fastmcp_the_server_is_disabled_not_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The desktop bundle ships without the mcp extra; it must still start.

        A hard dependency here would fail at first import inside PyInstaller, whose spec
        does not declare fastmcp's transitive backends.
        """
        import builtins

        import backend.mcp_server.server as server_mod

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "fastmcp" or name.startswith("fastmcp."):
                raise ImportError("simulated: extra not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        assert server_mod.mcp_available() is False
        assert server_mod.build_mcp_http_app() is None


@pytest.fixture
def designs_loaded():
    """Two runs of different methods, so per-method column resolution is exercised.

    bindcraft reports iptm as Average_i_pTM and rfd reports its (lower-is-better)
    pae_interaction under that name -- a selection spanning both is exactly where the
    REST API's raw column names stop working.
    """
    import backend.cache as cache_mod

    cache_mod.run_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.designs_cache.clear()

    cache_mod.run_cache["bc"] = {
        "run_id": "bc",
        "project_id": "proj",
        "method": "bindcraft",
        "metadata": {"name": "bc-run"},
        "pdb_files": ["/data/bc/d1.pdb", "/data/bc/d2.pdb"],
    }
    cache_mod.run_cache["rf"] = {
        "run_id": "rf",
        "project_id": "proj",
        "method": "rfd",
        "metadata": {"name": "rf-run"},
        "pdb_files": ["/data/rf/r1.pdb"],
    }
    cache_mod.designs_by_run_id["bc"] = [
        {
            "run_id": "bc",
            "design_id": "d1",
            "method": "bindcraft",
            "Average_i_pTM": 0.91234567,
            "Average_i_pAE": 7.5,
            "pdb_file": "/data/bc/d1.pdb",
            "Sequence": "AAAAAAAAAA",
        },
        {
            "run_id": "bc",
            "design_id": "d2",
            "method": "bindcraft",
            "Average_i_pTM": 0.55,
            "Average_i_pAE": 18.0,
            "pdb_file": "/data/bc/d2.pdb",
            "Sequence": "CCCCCCCCCC",
        },
    ]
    cache_mod.designs_by_run_id["rf"] = [
        {
            "run_id": "rf",
            "design_id": "r1",
            "method": "rfd",
            "pae_interaction": 6.0,
            "rmsd": 1.2,
            "pdb_file": "/data/rf/r1.pdb",
            "Sequence": "DDDDDDDDDD",
        }
    ]
    cache_mod._rebuild_flat_cache_from_index()
    yield
    cache_mod.run_cache.clear()
    cache_mod.designs_by_run_id.clear()
    cache_mod.designs_cache.clear()


class TestQueryDesigns:
    async def test_canonical_column_resolves_per_method(self, app, seeded, designs_loaded):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "query_designs",
                {"run_ids": ["bc", "rf"], "columns": ["iptm", "pae_interaction"], "limit": 10},
            )
        data = result.data
        rows = {r[data["columns"].index("design_id")]: r for r in data["rows"]}
        iptm = data["columns"].index("iptm")
        pae = data["columns"].index("pae_interaction")
        # bindcraft's Average_i_pTM and Average_i_pAE, rfd's pae_interaction.
        assert rows["d1"][iptm] == 0.9123  # four significant figures
        assert rows["d1"][pae] == 7.5
        assert rows["r1"][iptm] is None
        assert rows["r1"][pae] == 6.0

    async def test_server_paths_are_never_returned(self, app, seeded, designs_loaded):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool("query_designs", {"run_ids": ["bc"]})
        assert "pdb_file" not in result.data["columns"]
        row = result.data["rows"][0]
        assert "/data/bc/" not in str(row)
        filename = row[result.data["columns"].index("structure_filename")]
        assert filename in ("d1.pdb", "d2.pdb")

    async def test_wrong_sort_direction_warns_rather_than_lying(
        self, app, seeded, designs_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "query_designs",
                {"run_ids": ["rf"], "sort": "pae_interaction", "order": "desc"},
            )
        codes = {w["code"] for w in result.data["warnings"]}
        assert "SORT_DIRECTION_OVERRIDE" in codes

    async def test_unknown_column_suggests_alternatives(self, app, seeded, designs_loaded):
        with pytest.raises(Exception) as exc:
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "query_designs", {"run_ids": ["bc"], "columns": ["iptm_typo"]}
                )
        assert "UNKNOWN_COLUMN" in str(exc.value)

    async def test_oversized_request_is_refused_not_truncated(
        self, app, seeded, designs_loaded, monkeypatch
    ):
        import backend.mcp_server.tables as tables_mod

        monkeypatch.setattr(tables_mod, "MAX_CELLS", 1)
        with pytest.raises(Exception) as exc:
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool("query_designs", {"run_ids": ["bc"]})
        assert "RESPONSE_TOO_LARGE" in str(exc.value)

    async def test_empty_result_explains_the_filters(self, app, seeded, designs_loaded):
        with pytest.raises(Exception) as exc:
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "query_designs",
                    {
                        "run_ids": ["bc"],
                        "filters": [{"column": "iptm", "operator": ">", "threshold": 0.99}],
                    },
                )
        assert "EMPTY_SELECTION" in str(exc.value)


    async def test_canonical_name_that_is_also_a_raw_column_still_resolves(
        self, app, seeded, designs_loaded
    ):
        """`pae_interaction` is rfd's own column name AND the canonical name.

        Preferring the literal column returns rfd's values and null for bindcraft,
        which reads as missing data rather than a resolution failure.
        """
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "query_designs",
                {"run_ids": ["bc", "rf"], "columns": ["pae_interaction"], "limit": 10},
            )
        data = result.data
        pae = data["columns"].index("pae_interaction")
        design = data["columns"].index("design_id")
        values = {r[design]: r[pae] for r in data["rows"]}
        assert values == {"d1": 7.5, "d2": 18.0, "r1": 6.0}

    async def test_default_sort_is_iptm_desc_then_pae_asc(self, app, seeded, designs_loaded):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "query_designs", {"run_ids": ["bc", "rf"], "limit": 10}
            )
        data = result.data
        assert data["sorted_by"] == "default"
        order = [r[data["columns"].index("design_id")] for r in data["rows"]]
        # d1 (iptm 0.91) then d2 (0.55); r1 has no iptm at all, so it sorts after both
        # on pae_interaction rather than landing in arbitrary order.
        assert order == ["d1", "d2", "r1"]

    async def test_primary_score_sort_is_still_available(self, app, seeded, designs_loaded):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "query_designs",
                {"run_ids": ["bc", "rf"], "limit": 10, "sort": "primary_score"},
            )
        assert result.data["sorted_by"] == "primary_score"
        assert result.data["returned"] == 3


class TestSummarize:
    async def test_grouped_summary_reports_direction(self, app, seeded, designs_loaded):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "summarize_designs",
                {"run_ids": ["bc", "rf"], "columns": ["iptm"], "group_by": "method"},
            )
        groups = {g["group"]: g for g in result.data["groups"]}
        assert groups["bindcraft"]["columns"]["iptm"]["coverage"] == 2
        assert groups["bindcraft"]["columns"]["iptm"]["higher_is_better"] is True
        assert groups["rfd"]["columns"]["iptm"]["coverage"] == 0


class TestRanking:
    async def test_unresolvable_metric_is_an_error_not_a_silent_skip(
        self, app, seeded, designs_loaded
    ):
        with pytest.raises(Exception) as exc:
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "rank_designs",
                    {"run_ids": ["rf"], "metrics": [{"column": "hbonds"}]},
                )
        assert "NO_RANKABLE_METRICS" in str(exc.value)

    async def test_ranking_reports_what_each_metric_resolved_to(
        self, app, seeded, designs_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "rank_designs",
                {"run_ids": ["bc"], "metrics": [{"column": "iptm"}], "limit": 5},
            )
        resolved = result.data["metrics_resolved"]
        assert resolved[0]["column"] == "iptm"
        assert resolved[0]["higher_is_better"] is True
        assert resolved[0]["designs_with_value"] == 2


class TestDiversityAndSavedSets:
    async def test_missing_sequences_are_reported_not_silently_selected(
        self, app, seeded, designs_loaded
    ):
        import backend.cache as cache_mod

        for row in cache_mod.designs_by_run_id["bc"]:
            row["Sequence"] = None
        cache_mod._rebuild_flat_cache_from_index()

        with pytest.raises(Exception) as exc:
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "select_diverse_designs",
                    {"run_ids": ["bc"], "metrics": [{"column": "iptm"}], "budget": 2},
                )
        assert "SEQUENCES_REQUIRED" in str(exc.value)

    async def test_shortfall_against_budget_is_warned_about(
        self, app, seeded, designs_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "select_diverse_designs",
                {"run_ids": ["bc"], "metrics": [{"column": "iptm"}], "budget": 10},
            )
        codes = {w["code"] for w in result.data["warnings"]}
        assert "RESULT_SMALLER_THAN_BUDGET" in codes
        assert result.data["returned"] == 2

    async def test_save_as_creates_a_set_visible_to_the_rest_api(
        self, app, seeded, designs_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            created = await client.call_tool(
                "select_diverse_designs",
                {
                    "run_ids": ["bc"],
                    "metrics": [{"column": "iptm"}],
                    "budget": 2,
                    "save_as": "mcp panel",
                },
            )
            listed = await client.call_tool("saved_sets", {"action": "list"})

        assert created.data["saved_set_name"] == "mcp panel"
        names = {s["name"] for s in listed.data["saved_sets"]}
        assert "mcp panel" in names

        async with http_client(app) as http:
            resp = await http.get(
                "/api/saved-sets", headers={"Authorization": f"Bearer {seeded['token']}"}
            )
        assert resp.status_code == 200
        assert "mcp panel" in {s["name"] for s in resp.json()["saved_sets"]}

    async def test_saved_set_get_defaults_to_the_panel_not_the_pool(
        self, app, seeded, designs_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            created = await client.call_tool(
                "select_diverse_designs",
                {
                    "run_ids": ["bc"],
                    "metrics": [{"column": "iptm"}],
                    "budget": 1,
                    "save_as": "panel",
                },
            )
            panel = await client.call_tool(
                "saved_sets",
                {"action": "get", "saved_set_id": created.data["saved_set_id"]},
            )
            pool = await client.call_tool(
                "saved_sets",
                {
                    "action": "get",
                    "saved_set_id": created.data["saved_set_id"],
                    "in_diverse_set_only": False,
                },
            )
        assert panel.data["returned"] == 1
        assert pool.data["returned"] == 2
        assert "TRUNCATED" in {w["code"] for w in pool.data["warnings"]}

    async def test_create_from_design_keys_is_visible_to_rest(
        self, app, seeded, designs_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            created = await client.call_tool(
                "saved_sets",
                {
                    "action": "create",
                    "name": "hand pick",
                    "designs": [
                        {"run_id": "bc", "design_id": "d1"},
                        {"run_id": "rf", "design_id": "r1"},
                    ],
                },
            )
            listed = await client.call_tool("saved_sets", {"action": "list"})
            panel = await client.call_tool(
                "saved_sets",
                {"action": "get", "saved_set_id": created.data["saved_set_id"]},
            )

        assert created.data["name"] == "hand pick"
        assert created.data["design_count"] == 2
        names = {s["name"] for s in listed.data["saved_sets"]}
        assert "hand pick" in names

        columns = panel.data["columns"]
        ids = {r[columns.index("design_id")] for r in panel.data["rows"]}
        assert ids == {"d1", "r1"}
        assert all(r[columns.index("in_diverse_set")] for r in panel.data["rows"])

        async with http_client(app) as http:
            resp = await http.get(
                "/api/saved-sets", headers={"Authorization": f"Bearer {seeded['token']}"}
            )
        assert resp.status_code == 200
        assert "hand pick" in {s["name"] for s in resp.json()["saved_sets"]}

    async def test_create_unknown_design_is_an_error(self, app, seeded, designs_loaded):
        with pytest.raises(Exception, match="DESIGN_NOT_FOUND"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "saved_sets",
                    {
                        "action": "create",
                        "name": "missing",
                        "designs": [{"run_id": "bc", "design_id": "nope"}],
                    },
                )

    async def test_create_ambiguous_design_is_an_error(self, app, seeded, designs_loaded):
        import backend.cache as cache_mod

        cache_mod.run_cache["merged"] = {
            "run_id": "merged",
            "project_id": "proj",
            "method": "bindcraft",
            "metadata": {"name": "merged-run"},
            "merged": True,
            "pdb_files": [],
        }
        cache_mod.designs_by_run_id["merged"] = [
            {
                "run_id": "merged",
                "design_id": "d1",
                "method": "bindcraft",
                "source_path": "/a",
            },
            {
                "run_id": "merged",
                "design_id": "d1",
                "method": "bindcraft",
                "source_path": "/b",
            },
        ]
        cache_mod._rebuild_flat_cache_from_index()

        with pytest.raises(Exception, match="AMBIGUOUS_DESIGN_REF"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "saved_sets",
                    {
                        "action": "create",
                        "name": "ambig",
                        "designs": [{"run_id": "merged", "design_id": "d1"}],
                    },
                )

    async def test_create_without_designs_is_an_error(self, app, seeded, designs_loaded):
        with pytest.raises(Exception, match="INVALID_SAVED_SET_REQUEST"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "saved_sets",
                    {"action": "create", "name": "empty", "designs": []},
                )


def _persist_cache_designs(repo) -> None:
    """Write the in-memory cache into sqlite so merge-table can match designs."""
    import backend.cache as cache_mod

    for run_id, run in list(cache_mod.run_cache.items()):
        designs = list(cache_mod.designs_by_run_id.get(run_id) or [])
        project = str(run.get("project_id") or "proj")
        repo.upsert_run_and_replace_designs(f"{project}/{run_id}", run_id, dict(run), designs)


class TestMergeDesignColumns:
    async def test_preview_then_apply_adds_a_column(self, app, seeded, designs_loaded):
        _persist_cache_designs(seeded["repo"])
        table = "design_id\tlab_score\nd1\t1.5\nd3\t9.0\n"

        async with mcp_client(app, seeded["token"]) as client:
            preview = await client.call_tool(
                "merge_design_columns",
                {
                    "run_ids": ["bc"],
                    "table": table,
                    "preview": True,
                },
            )
            assert preview.data["preview"] is True
            assert preview.data["matched_design_count"] == 1
            assert preview.data["unknown_design_id_count"] == 1
            assert "lab_score" in preview.data["new_columns"]

            with pytest.raises(Exception, match="UNKNOWN_COLUMN"):
                await client.call_tool(
                    "query_designs",
                    {"run_ids": ["bc"], "columns": ["lab_score"], "limit": 10},
                )

            applied = await client.call_tool(
                "merge_design_columns",
                {
                    "run_ids": ["bc"],
                    "table": table,
                    "preview": False,
                },
            )
            assert applied.data["preview"] is False
            assert applied.data["updated"] >= 1

            after = await client.call_tool(
                "query_designs",
                {"run_ids": ["bc"], "columns": ["lab_score"], "limit": 10},
            )
            rows = {r[after.data["columns"].index("design_id")]: r for r in after.data["rows"]}
            score = after.data["columns"].index("lab_score")
            assert rows["d1"][score] == 1.5
            assert rows["d2"][score] is None

            described = await client.call_tool(
                "describe_columns",
                {"run_ids": ["bc"], "include_raw": True},
            )
        names = {c["name"] for c in described.data["columns"]}
        assert "lab_score" in names

    async def test_empty_table_is_an_error(self, app, seeded, designs_loaded):
        with pytest.raises(Exception, match="INVALID_MERGE_TABLE"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "merge_design_columns",
                    {"run_ids": ["bc"], "table": ""},
                )

    async def test_missing_design_id_column_is_an_error(self, app, seeded, designs_loaded):
        _persist_cache_designs(seeded["repo"])
        with pytest.raises(Exception, match="INVALID_MERGE_TABLE"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "merge_design_columns",
                    {"run_ids": ["bc"], "table": "batch\nB1\n"},
                )


class TestDiscoveryTools:
    async def test_describe_methods_states_sort_directions(self, app, seeded):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool("describe_methods", {})
        by_name = {m["canonical"]: m for m in result.data["metrics"]}
        assert by_name["iptm"]["higher_is_better"] is True
        assert by_name["pae_interaction"]["higher_is_better"] is False
        assert "iptm" in result.data["ranking_presets"]

    async def test_list_runs_reads_the_shared_cache(self, app, seeded):
        import backend.cache as cache_mod

        cache_mod.run_cache.clear()
        cache_mod.run_cache["run-1"] = {
            "run_id": "run-1",
            "project_id": "proj",
            "method": "bindcraft",
            "metadata": {"name": "campaign-a", "target": "UL119"},
            "pdb_files": ["/data/runs/a/x.pdb"],
        }
        try:
            async with mcp_client(app, seeded["token"]) as client:
                result = await client.call_tool("list_runs", {})
        finally:
            cache_mod.run_cache.clear()

        assert result.data["total_runs"] == 1
        run = result.data["runs"][0]
        assert run["run_id"] == "run-1"
        assert run["method"] == "bindcraft"
        assert run["structure_count"] == 1
        assert run["design_count"] == 1  # no-DB/cache miss → structure_count fallback
        assert "download_token=" in run["designs_json_url"]
        assert "/api/designs?run_ids=run-1" in run["designs_json_url"]
        base = result.data.get("base_url")
        if base:
            assert run["designs_json_url"].startswith(base + "/api/designs?run_ids=run-1")
        assert "format=tsv" in run["designs_tsv_url"]
        assert "download_token=" in run["designs_tsv_url"]

    async def test_list_runs_design_count_from_db_without_loading_cache(
        self, app, seeded
    ):
        """design_count must work from a cheap COUNT(*) without designs_by_run_id."""
        import backend.cache as cache_mod

        repo = seeded["repo"]
        run_dict = {
            "run_id": "bc-db",
            "project_id": "UL119",
            "method": "bindcraft",
            "metadata": {"name": "bc-ul119-long-name", "target": "UL119"},
            "pdb_files": [],
        }
        designs = [
            {
                "run_id": "bc-db",
                "design_id": f"d{i}",
                "project_id": "UL119",
                "method": "bindcraft",
                "Average_i_pTM": 0.8,
            }
            for i in range(3)
        ]
        repo.upsert_run_and_replace_designs("UL119/bc-ul119", "bc-db", run_dict, designs)

        cache_mod.run_cache.clear()
        cache_mod.designs_by_run_id.clear()
        cache_mod.designs_cache.clear()
        cache_mod.run_cache["bc-db"] = run_dict
        try:
            async with mcp_client(app, seeded["token"]) as client:
                result = await client.call_tool("list_runs", {})
        finally:
            cache_mod.run_cache.clear()
            cache_mod.designs_by_run_id.clear()
            cache_mod.designs_cache.clear()

        assert "bc-db" not in cache_mod.designs_by_run_id
        run = result.data["runs"][0]
        assert run["design_count"] == 3
        assert run["structure_count"] == 0
        assert run["ingested_at"] is not None
        assert "download_token=" in run["designs_tsv_url"]

    async def test_list_runs_filters(self, app, seeded):
        import backend.cache as cache_mod

        cache_mod.run_cache.clear()
        cache_mod.run_cache["bc"] = {
            "run_id": "bc",
            "project_id": "UL119",
            "method": "bindcraft",
            "metadata": {"name": "bc-ul119-v1", "target": "UL119"},
            "pdb_files": ["/a.pdb"],
        }
        cache_mod.run_cache["rf"] = {
            "run_id": "rf",
            "project_id": "UL119",
            "method": "rfd3",
            "metadata": {"name": "rf3-ul119-v1", "target": "UL119"},
            "pdb_files": ["/b.pdb"],
        }
        cache_mod.run_cache["other"] = {
            "run_id": "other",
            "project_id": "SpeA",
            "method": "bindcraft",
            "metadata": {"name": "bc-spea", "target": "SpeA"},
            "pdb_files": ["/c.pdb"],
        }
        try:
            async with mcp_client(app, seeded["token"]) as client:
                by_method = await client.call_tool(
                    "list_runs", {"methods": ["rfd3"]}
                )
                by_name = await client.call_tool(
                    "list_runs", {"name_contains": "ul119"}
                )
                by_project = await client.call_tool(
                    "list_runs", {"project_id": "SpeA"}
                )
                by_ids = await client.call_tool(
                    "list_runs", {"run_ids": ["bc", "rf"]}
                )
        finally:
            cache_mod.run_cache.clear()

        assert {r["run_id"] for r in by_method.data["runs"]} == {"rf"}
        assert {r["run_id"] for r in by_name.data["runs"]} == {"bc", "rf"}
        assert {r["run_id"] for r in by_project.data["runs"]} == {"other"}
        assert {r["run_id"] for r in by_ids.data["runs"]} == {"bc", "rf"}


@pytest.fixture
def target_contacts_loaded(monkeypatch, designs_loaded):
    """A resolved target over both runs, with contacts for two of the three designs.

    The seeded runs point at structure files that do not exist, so the real resolver
    would report an error for every run. Substituting the resolved context and the
    cached records exercises the tool surface -- residue catalogue, profile ordering,
    contact conditions as hard filters -- without needing structures on disk.
    """
    import backend.filtering.target_contacts_service as tcs
    from backend.filtering.schemas import TargetResidueDto
    from backend.filtering.target_contacts import ResidueContact

    residues = [
        TargetResidueDto(
            label=f"A{100 + i}", chain="A", resseq=100 + i, icode=" ",
            resname=name, aa1=aa, sasa_apo=sasa,
        )
        for i, (name, aa, sasa) in enumerate(
            [("GLU", "E", 150.0), ("TYR", "Y", 120.0), ("LEU", "L", 80.0)]
        )
    ]

    def context(run_id: str, *, refresh: bool = False):
        return tcs.RunContext(
            run_id=run_id,
            run_name=f"{run_id}-run",
            method="bindcraft" if run_id == "bc" else "rfd",
            binder_chain_ids=["B"],
            target_chain_ids=["A"],
            target_key="target-1",
            residues=residues,
        )

    # d1 buries A100 and touches A101; r1 sits away from the whole epitope. d2 has no
    # record at all, which is how an uncomputed design looks to a contact condition.
    records = {
        tcs._design_key("bc", "d1"): {
            "A100": ResidueContact(d_ca=6.0, d_cb=5.0, d_heavy=2.5, sasa_bound=30.0),
            "A101": ResidueContact(d_ca=9.0, d_cb=8.2, d_heavy=4.5, sasa_bound=110.0),
        },
        tcs._design_key("rf", "r1"): {
            "A100": ResidueContact(d_ca=11.5, d_cb=11.0, d_heavy=10.5, sasa_bound=150.0),
        },
    }

    monkeypatch.setattr(tcs, "get_run_context", context)
    monkeypatch.setattr(
        tcs,
        "load_contact_data",
        lambda run_ids: tcs.ContactData(
            records=records, contexts={r: context(r) for r in run_ids}
        ),
    )
    yield


class TestTargetContacts:
    async def test_the_contact_tools_are_registered(self, app, seeded):
        async with mcp_client(app, seeded["token"]) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert {"list_target_residues", "target_contact_profile"} <= names

    async def test_list_target_residues_gives_labels_to_filter_on(
        self, app, seeded, target_contacts_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "list_target_residues", {"run_ids": ["bc", "rf"]}
            )
        targets = result.data["targets"]
        assert len(targets) == 1, "runs sharing a target must group into one entry"
        assert set(targets[0]["run_ids"]) == {"bc", "rf"}
        assert targets[0]["sequence"] == "EYL"
        assert [r[0] for r in targets[0]["residues"]] == ["A100", "A101", "A102"]

    async def test_uncomputed_designs_are_a_warning_not_a_silent_gap(
        self, app, seeded, target_contacts_loaded
    ):
        """A design with no record fails every contact condition, so silence here would
        read as a harsh threshold rather than missing data."""
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "list_target_residues", {"run_ids": ["bc", "rf"], "include_residues": False}
            )
        codes = {w["code"] for w in result.data["warnings"]}
        assert "TARGET_CONTACTS_UNAVAILABLE" in codes

    async def test_unresolvable_target_is_an_error_naming_the_runs(
        self, app, seeded, designs_loaded
    ):
        with pytest.raises(Exception, match="EMPTY_SELECTION"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool("list_target_residues", {"run_ids": ["bc"]})

    async def test_profile_ranks_the_epitope_first(
        self, app, seeded, target_contacts_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "target_contact_profile",
                {"run_ids": ["bc", "rf"], "target_key": "target-1", "metric": "delta_sasa"},
            )
        labels = [row[0] for row in result.data["rows"]]
        assert labels[0] == "A100", "the most-buried residue must come first"
        assert "A102" not in labels, "residues no binder approaches are omitted"
        assert result.data["n_designs"] == 2

    async def test_contact_condition_filters_query_designs(
        self, app, seeded, target_contacts_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "query_designs",
                {
                    "run_ids": ["bc", "rf"],
                    "target_contact_groups": [
                        {
                            "target_key": "target-1",
                            "filters": [
                                {
                                    "residues": ["A100"],
                                    "scope": "any",
                                    "metric": "distance",
                                    "distance_type": "heavy",
                                    "operator": "<=",
                                    "value": 5.0,
                                }
                            ],
                        }
                    ],
                },
            )
        columns = result.data["columns"]
        rows = result.data["rows"]
        assert not any(c.startswith("__tc_") for c in columns), "virtual columns leaked"
        design_ids = {row[columns.index("design_id")] for row in rows}
        assert design_ids == {"d1"}, "only the design contacting A100 should survive"

    async def test_rank_designs_labels_the_contact_stage_readably(
        self, app, seeded, target_contacts_loaded
    ):
        async with mcp_client(app, seeded["token"]) as client:
            result = await client.call_tool(
                "rank_designs",
                {
                    "run_ids": ["bc", "rf"],
                    "metrics": [{"column": "iptm"}],
                    "target_contact_groups": [
                        {
                            "target_key": "target-1",
                            "label": "PD-L1",
                            "filters": [
                                {
                                    "residues": ["A100"],
                                    "metric": "distance",
                                    "operator": "<=",
                                    "value": 5.0,
                                }
                            ],
                        }
                    ],
                },
            )
        stage = result.data["filter_cascade"][0]["column"]
        assert not stage.startswith("__tc_"), stage
        assert "A100" in stage and "PD-L1" in stage

    async def test_an_empty_contact_result_says_contacts_may_be_uncomputed(
        self, app, seeded, target_contacts_loaded
    ):
        with pytest.raises(Exception, match="Compute target contacts"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "query_designs",
                    {
                        "run_ids": ["bc", "rf"],
                        "target_contact_groups": [
                            {
                                "target_key": "target-1",
                                "filters": [
                                    {
                                        "residues": ["A100"],
                                        "metric": "distance",
                                        "operator": "<=",
                                        "value": 0.1,
                                    }
                                ],
                            }
                        ],
                    },
                )

    async def test_malformed_contact_group_is_rejected_with_a_next_call(
        self, app, seeded, target_contacts_loaded
    ):
        with pytest.raises(Exception, match="INVALID_TARGET_CONTACT_FILTER"):
            async with mcp_client(app, seeded["token"]) as client:
                await client.call_tool(
                    "query_designs",
                    {
                        "run_ids": ["bc"],
                        "target_contact_groups": [
                            {"target_key": "target-1", "filters": [{"metric": "nonsense"}]}
                        ],
                    },
                )
