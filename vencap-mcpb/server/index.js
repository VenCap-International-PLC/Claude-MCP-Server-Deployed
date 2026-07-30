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
        "Query VenCap portfolio data (NAV, capital calls, distributions, " +
        "fund performance, portfolio exposure, investor transactions, " +
        "stock holdings, IPO data, share valuations). Only SELECT " +
        "statements are permitted; enforced centrally.",
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
      arguments: { query, database, api_key: API_KEY },
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