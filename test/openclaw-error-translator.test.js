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

  it("does not classify billing-looking conversation text as provider billing", () => {
    assert.equal(
      classifyProviderError({
        source: "conversation",
        message: "用户在群里问：HTTP 402 insufficient balance 是什么意思？"
      }).kind,
      "unknown"
    );
  });

  it("classifies structured provider errors by status before text fallback", () => {
    assert.equal(
      classifyProviderError({
        source: "provider_error",
        provider: "minimax",
        status: 402,
        message: "Payment required"
      }).kind,
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
      error: {
        source: "provider_error",
        status: 402,
        message: "MiniMax API error (402): insufficient balance"
      }
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
        error: {
          source: "provider_error",
          message: "network timeout"
        }
      }),
      null
    );
  });

  it("does not format conversation text that mentions billing keywords", () => {
    assert.equal(
      formatReadableProviderError({
        provider: "minimax",
        error: {
          source: "conversation",
          message: "HTTP 402 insufficient balance 是什么报错？"
        }
      }),
      null
    );
  });
});
