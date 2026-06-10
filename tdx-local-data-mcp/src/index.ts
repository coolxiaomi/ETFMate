#!/usr/bin/env node
/**
 * MCP Server 入口
 * 使用 stdio transport 启动
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerTools } from "./mcp/tools.js";
import { loadConfig } from "./config/appConfig.js";
import { getDb, closeDb } from "./db/sqlite.js";

async function main(): Promise<void> {
  // 1. 加载配置
  const config = loadConfig();

  // 2. 初始化数据库（自动建表）
  getDb();

  // 3. 创建 MCP Server
  const server = new McpServer({
    name: "tdx-local-data-mcp",
    version: "1.0.0",
  });

  // 4. 注册 Tools
  registerTools(server);

  // 5. 启动 stdio transport
  const transport = new StdioServerTransport();
  await server.connect(transport);

  // 输出到 stderr（stdout 用于 MCP 通信）
  console.error(
    `[tdx-local-data-mcp] Server started. TDX path: ${config.tdxInstallPath}`
  );
  console.error(`[tdx-local-data-mcp] SQLite: ${config.sqlitePath}`);
}

// 优雅退出
process.on("SIGINT", () => {
  closeDb();
  process.exit(0);
});

process.on("SIGTERM", () => {
  closeDb();
  process.exit(0);
});

main().catch((err) => {
  console.error("[tdx-local-data-mcp] Fatal error:", err);
  closeDb();
  process.exit(1);
});
