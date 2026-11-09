# ShopAssist MCP integration

ShopAssist exposes a local stdio MCP server from `src.mcp_server`. It demonstrates interoperability with the official Python MCP SDK while keeping account authorization in ShopAssist's existing session service.

## Available tools

- `search_products(query, category, in_stock)`: public catalog search; returns at most ten products.
- `lookup_order(order_id)`: private order lookup. The tool reads `MCP_CUSTOMER_SESSION_TOKEN` from the server process, validates it through `AuthService`, then scopes the lookup to that account. The caller cannot supply an email to choose an account.

## Start

Install the Python dependencies, set a valid ShopAssist bearer session token in `MCP_CUSTOMER_SESSION_TOKEN`, then run:

```powershell
python -m src.mcp_server
```

The server uses MCP stdio transport. Diagnostics should go to stderr so stdout remains protocol-only. Integrate it with a local MCP host using the host's Python command and project working directory. Do not pass a customer token to an untrusted MCP host or commit it to configuration.

## Verification

`evaluation/mcp_smoke.py` exercises discovery and tool calls with the official SDK in process. `evaluation/mcp_security_checks.py` additionally checks missing/invalid session rejection, customer ownership, and non-disclosure for another customer's order. These checks use generated fixture data in a temporary SQLite database; they do not establish production security or a remote MCP transport deployment.

Run the security checks with:

```powershell
python -m evaluation.mcp_security_checks
```
