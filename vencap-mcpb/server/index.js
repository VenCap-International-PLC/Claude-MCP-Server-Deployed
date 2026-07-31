#!/usr/bin/env node
/**
 * VenCap MCP thin client.
 * Runs on each analyst's laptop, launched by Claude Desktop over stdio.
 * Holds NO database credentials and NO SQL logic.
 *
 * Tool definitions are fetched FROM the central server at runtime, so the
 * tool description can be changed centrally (edit the run_sql docstring in
 * mcp_server.py, restart the server) without repackaging or redistributing
 * this extension.
 *
 * If the central server is unreachable (analyst off-VPN), a stub tool is
 * exposed instead, which returns a clear "connect to the VPN" message.
 * This is deliberate: if no tool were exposed at all, Claude would answer
 * from general knowledge instead of telling the analyst what is wrong.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { SSEClientTransport } from "@modelcontextprotocol/sdk/client/sse.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// Injected by Claude Desktop from user_config (see manifest.json)
const SERVER_URL = process.env.VENCAP_SERVER_URL;
const API_KEY = process.env.VENCAP_API_KEY;

// Windows identity of the person running this extension. Captured here on
// the analyst's own machine and forwarded with each call so the central
// audit log records WHO ran each query, not just what was run.
const WINDOWS_USER = (() => {
  const domain = process.env.USERDOMAIN || "";
  const name = process.env.USERNAME || "unknown";
  return domain ? `${domain}\\${name}` : name;
})();

if (!SERVER_URL || !API_KEY) {
  console.error(
    "VenCap MCP client: missing configuration. " +
      "VENCAP_SERVER_URL and VENCAP_API_KEY must be set via extension settings."
  );
  process.exit(1);
}

// How long to wait for the central server before falling back to the
// offline stub. Kept short so an off-VPN analyst is not left hanging.
const CONNECT_TIMEOUT_MS = 5000;

// Parameters the thin client supplies itself. These are stripped from the
// schema shown to Claude so it never sees, reasons about, or supplies them.
const INTERNAL_PARAMS = ["api_key", "user"];

// Message shown when the central server cannot be reached.
const OFFLINE_MESSAGE =
  "Unable to reach the VenCap data server. This tool only works while " +
  "connected to the VenCap VPN or office network. Please check your " +
  "connection and try again.";

// ── Connection to the central MCP server ────────────────────────────────────
let remoteClient = null;

async function getRemoteClient() {
  if (remoteClient) return remoteClient;

  const transport = new SSEClientTransport(new URL(SERVER_URL));
  const client = new Client(
    { name: "vencap-mcp-thin-client", version: "0.4.0" },
    { capabilities: {} }
  );

  await client.connect(transport);
  remoteClient = client;
  return remoteClient;
}

function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms)
    ),
  ]);
}

// ── Tool definitions ────────────────────────────────────────────────────────
// Remove the parameters this client injects, so Claude never sees them.
function stripInternalParams(tool) {
  const schema = tool.inputSchema ? { ...tool.inputSchema } : {};

  if (schema.properties) {
    schema.properties = { ...schema.properties };
    for (const param of INTERNAL_PARAMS) {
      delete schema.properties[param];
    }
  }
  if (Array.isArray(schema.required)) {
    schema.required = schema.required.filter(
      (name) => !INTERNAL_PARAMS.includes(name)
    );
  }

  return { ...tool, inputSchema: schema };
}

// Used only when the central server cannot be reached.
const OFFLINE_TOOLS = [
  {
    name: "run_sql",
    description:
      "Query VenCap portfolio and investor data. NOTE: the VenCap data " +
      "server is currently unreachable — this tool requires a connection " +
      "to the VenCap VPN or office network. If the user asks a data " +
      "question, tell them they need to connect to the VPN. Do not attempt " +
      "to answer VenCap data questions from general knowledge.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "A valid SQL SELECT statement." },
        database: {
          type: "string",
          enum: ["gp", "lp"],
          description: "'gp' for fund-level data, 'lp' for investor-level data.",
        },
      },
      required: ["query", "database"],
    },
  },
];

let cachedTools = null;

async function getTools() {
  if (cachedTools) return cachedTools;

  try {
    const client = await withTimeout(
      getRemoteClient(),
      CONNECT_TIMEOUT_MS,
      "Connection to VenCap server"
    );
    const result = await withTimeout(
      client.listTools(),
      CONNECT_TIMEOUT_MS,
      "Tool listing"
    );

    cachedTools = (result.tools || []).map(stripInternalParams);
    return cachedTools;
  } catch (err) {
    // Do NOT cache the offline list — the analyst may connect to the VPN
    // later in the session, and the next attempt should try the server again.
    console.error(
      `VenCap MCP client: could not fetch tools from server (${err.message}). ` +
        `Serving offline stub.`
    );
    remoteClient = null;
    return OFFLINE_TOOLS;
  }
}

// ── Local stdio server exposed to Claude Desktop ────────────────────────────
const server = new Server(
  { name: "vencap-mcp-client", version: "0.4.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: await getTools(),
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  // The API key and Windows username are attached HERE, by the thin client,
  // from its own securely stored config — never supplied by Claude.
  const attempt = async () => {
    const client = await getRemoteClient();
    return await client.callTool({
      name,
      arguments: { ...(args ?? {}), api_key: API_KEY, user: WINDOWS_USER },
    });
  };

  try {
    return await attempt();
  } catch (err) {
    // The cached connection may be stale — e.g. the central server was
    // restarted. Discard it and try once more before surfacing an error.
    remoteClient = null;
    cachedTools = null;
    try {
      return await attempt();
    } catch (retryErr) {
      return {
        content: [{ type: "text", text: `${OFFLINE_MESSAGE}\n\n(${retryErr.message})` }],
        isError: true,
      };
    }
  }
});

// ── Start ────────────────────────────────────────────────────────────────────
const transport = new StdioServerTransport();
await server.connect(transport);