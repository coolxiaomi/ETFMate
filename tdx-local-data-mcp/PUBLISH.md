# npm 发布指南

## 前置准备

### 1. 登录 npm

```bash
npm login --registry=https://registry.npmjs.org/
```

验证登录状态：

```bash
npm whoami --registry=https://registry.npmjs.org/
```

### 2. 更新版本号

发布前需要更新 `package.json` 中的版本号：

```bash
# 补丁版本 (1.0.0 -> 1.0.1)
npm version patch

# 次要版本 (1.0.0 -> 1.1.0)
npm version minor

# 主要版本 (1.0.0 -> 2.0.0)
npm version major
```

---

## 发布流程

### 方式一：完整发布（推荐）

```bash
# 1. 构建
pnpm build

# 2. 发布到 npm
npm publish
```

### 方式二：预发布测试

```bash
# 查看将要发布的文件
npm pack --dry-run

# 实际打包（生成 .tgz 文件）
npm pack

# 发布
npm publish
```

### 方式三：发布 Beta 版本

```bash
# 更新版本号为 beta
npm version 1.1.0-beta.1

# 发布到 beta tag
npm publish --tag beta
```

---

## 发布后验证

### 检查发布状态

```bash
npm view tdx-local-data-mcp
```

### 用户安装使用

用户安装后，在 MCP 客户端中配置：

```json
{
  "mcpServers": {
    "tdx-local-data-mcp": {
      "command": "npx",
      "args": ["-y", "tdx-local-data-mcp"],
      "env": {
        "TDX_INSTALL_PATH": "C:\\zd_hbzq"
      }
    }
  }
}
```

---

## 发布前检查清单

- [ ] `pnpm build` 编译通过
- [ ] `node dist/index.js` 可以正常启动（需配置 .env）
- [ ] 版本号已更新
- [ ] `package.json` 中 `repository.url` 已更新为真实地址
- [ ] CHANGELOG 已更新（如有）

---

## 常见问题

### Q: 发布时提示 "You must be logged in"

```bash
npm login --registry=https://registry.npmjs.org/
```

### Q: 发布时提示 "Cannot publish over previously published version"

版本号已被占用，需要更新版本号：

```bash
npm version patch
npm publish
```

### Q: 如何撤回已发布的版本

```bash
# 撤回指定版本（72小时内可撤回）
npm unpublish tdx-local-data-mcp@1.0.0

# 标记为废弃（不删除，但提示用户升级）
npm deprecate tdx-local-data-mcp@1.0.0 "请使用 1.1.0 版本"
```

### Q: better-sqlite3 原生模块问题

better-sqlite3 包含 C++ 原生模块，用户安装时需要编译环境。如果用户安装失败，建议：

1. 安装 Windows Build Tools
2. 或使用预编译的 binary

---

## 版本管理规范

建议使用语义化版本（SemVer）：

- **MAJOR**（主版本）：不兼容的 API 更改
- **MINOR**（次版本）：向后兼容的功能新增
- **PATCH**（补丁版本）：向后兼容的 Bug 修复
