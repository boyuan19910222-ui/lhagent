import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  classifyProviderError,
  formatReadableProviderError,
  resolveProviderRule
} from "../src/openclaw-error-translator.js";

describe("OpenClaw provider error translator", () => {
  it("classifies billing errors from English provider responses", () => {
    assert.equal(
      classifyProviderError("MiniMax API error (402): insufficient balance").kind,
      "billing"
    );
  });

  it("classifies billing errors from Chinese provider responses", () => {
    assert.equal(classifyProviderError("账户余额不足，请充值后重试").kind, "billing");
  });

  it("classifies overdue-balance provider responses as billing", () => {
    assert.equal(
      classifyProviderError("403 The request failed because your account has an overdue balance").kind,
      "billing"
    );
  });

  it("resolves MiniMax from provider id or raw error", () => {
    assert.equal(resolveProviderRule("minimax")?.id, "minimax");
    assert.equal(resolveProviderRule("", "MiniMax API error")?.id, "minimax");
  });

  it("formats a beginner-readable MiniMax billing message", () => {
    const message = formatReadableProviderError({
      provider: "minimax",
      model: "abab6.5-chat",
      rawError: "MiniMax API error (402): insufficient balance"
    });

    assert.match(message, /MiniMax 模型服务余额不足或账户欠费/u);
    assert.match(message, /abab6\.5-chat/u);
    assert.match(message, /platform\.minimaxi\.com\/console\/recharge-records/u);
  });

  it("formats a beginner-readable Volcengine Ark billing message", () => {
    const message = formatReadableProviderError({
      provider: "doubao",
      model: "doubao-seed-2-0-pro-260215",
      rawError: "403 The request failed because your account has an overdue balance"
    });

    assert.match(message, /火山引擎方舟\/豆包模型服务返回了账单错误/u);
    assert.match(message, /doubao-seed-2-0-pro-260215/u);
    assert.match(message, /console\.volcengine\.com\/ark\/region:ark\+cn-beijing\/apiKey/u);
  });

  it("leaves unrelated errors untouched", () => {
    assert.equal(
      formatReadableProviderError({
        provider: "minimax",
        rawError: "network timeout"
      }),
      null
    );
  });
});
