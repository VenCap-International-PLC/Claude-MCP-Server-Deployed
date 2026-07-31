#!/usr/bin/env node
/**
 * VenCap MCP thin client.
 * Runs on each analyst's laptop, launched by Claude Desktop over stdio.
 * Holds NO database credentials and NO SQL logic.
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
// Windows identity of the person running this extension.
// Captured here on the analyst's own machine and forwarded with each call
// so the central audit log records WHO ran each query, not just what was run.
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

// Lazy, reused connection to the central MCP server
let remoteClient = null;

async function getRemoteClient() {
  if (remoteClient) return remoteClient;

  const transport = new SSEClientTransport(new URL(SERVER_URL));
  const client = new Client(
    { name: "vencap-mcp-thin-client", version: "0.1.0" },
    { capabilities: {} }
  );

  await client.connect(transport);
  remoteClient = client;
  return remoteClient;
}

// Local stdio server exposed to Claude Desktop
const server = new Server(
  { name: "vencap-mcp-client", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

// What Claude sees: no api_key parameter, on purpose.
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "run_sql",
      description:
        "Query VenCap portfolio and investor data. Only SELECT statements " +
        "are permitted.\n\n" +
        "DATABASE ROUTING — choose by PERSPECTIVE, not by keyword:\n" +
        "• 'gp' = FUND perspective. VenCap's funds-of-funds and the venture " +
        "funds they invest into. Schemas: bot.* and pbi.*\n" +
        "  Use for: fund NAV, capital calls VenCap paid to VFs, distributions " +
        "VenCap received, portfolio company exposure, commitments to VFs, VF " +
        "metadata, and stock pipeline / IPO / share valuation data (pbi.*).\n" +
        "• 'lp' = INVESTOR perspective. External investors in VenCap's own " +
        "FoFs. Schema: bot.* ONLY — never reference pbi.* for lp.\n" +
        "  Use for: calls VenCap made to its investors, distributions paid to " +
        "investors, investor commitments, fees, investor profiles, geography.\n\n" +
        "The same word means different things depending on perspective:\n" +
        "  'capital calls VenCap 16 paid to Sequoia'  -> gp\n" +
        "  'capital calls VenCap 16 made to its LPs'  -> lp\n" +
        "  'NAV of VenCap 16'                         -> gp\n" +
        "  'net value for Church Commissioners'       -> lp\n\n" +
        "If the perspective is genuinely ambiguous, ASK the user before " +
        "querying. Never tell the user which database was used — routing is " +
        "internal only.",
      inputSchema: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description:
              "A valid SQL SELECT statement. GP queries may use bot.* " +
              "and pbi.* schemas. LP queries may only use bot.* schema.",
          },
          database: {
            type: "string",
            enum: ["gp", "lp"],
            description:
              "'gp' for fund-level data (bot.* and pbi.* schemas), " +
              "'lp' for investor-level data (bot.* schema only).",
          },
        },
        required: ["query", "database"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name !== "run_sql") {
    throw new Error(`Unknown tool: ${request.params.name}`);
  }

  const { query, database } = request.params.arguments ?? {};

  try {
    const client = await getRemoteClient();

    // The API key is attached HERE, by the thin client, from its own
    // securely stored config - never supplied by Claude.
    const result = await client.callTool({
      name: "run_sql",
      arguments: { query, database, api_key: API_KEY, user: WINDOWS_USER },
    });

    return result;
  } catch (err) {
    return {
      content: [
        {
          type: "text",
          text:
            `Error reaching the VenCap MCP server: ${err.message}\n` +
            `Check that you are connected to the VenCap VPN or office network.`,
        },
      ],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);