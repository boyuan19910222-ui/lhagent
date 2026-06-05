const BILLING_PATTERNS = [
  /\b(?:http\s*)?402\b/i,
  /payment required/i,
  /insufficient[_\s-]*(?:credits|quota|balance)/i,
  /credit balance/i,
  /(?:spend|spending) limit/i,
  /used all available credits/i,
  /overdue balance/i,
  /account has an overdue balance/i,
  /余额不足/u,
  /账户余额不足/u,
  /欠费/u,
  /账户已欠费/u
];

const PROVIDER_RULES = [
  {
    id: "minimax",
    label: "MiniMax",
    match: /mini\s*max|minimax|minimaxi/i,
    billingUrl: "https://platform.minimaxi.com/console/recharge-records",
    action: "请打开 MiniMax 平台充值或续费，然后回到当前对话重试。"
  },
  {
    id: "volcengine-ark",
    label: "火山引擎方舟",
    match: /doubao|volcengine|ark|tencenthytokenplan|\bhy\d?/i,
    billingUrl: "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    action: "请打开火山引擎方舟 API 管理页，检查账号状态、API Key 和计费配置，然后回到当前对话重试。"
  }
];

export function classifyProviderError(rawError) {
  const text = String(rawError ?? "").trim();
  if (!text) return { kind: "unknown" };

  if (BILLING_PATTERNS.some((pattern) => pattern.test(text))) {
    return { kind: "billing" };
  }

  return { kind: "unknown" };
}

export function resolveProviderRule(provider, rawError = "") {
  const haystack = `${provider ?? ""}\n${rawError ?? ""}`;
  return PROVIDER_RULES.find((rule) => rule.match.test(haystack));
}

export function formatReadableProviderError({ rawError, provider, model }) {
  const classification = classifyProviderError(rawError);
  const rule = resolveProviderRule(provider, rawError);

  if (classification.kind === "billing") {
    if (rule?.id === "minimax") {
      return [
        "⚠️ MiniMax 模型服务余额不足或账户欠费，OpenClaw 暂时无法继续回复。",
        "",
        `当前模型：${model || "MiniMax"}`,
        `处理方式：${rule.action}`,
        `充值入口：${rule.billingUrl}`,
        "",
        "如果已经充值仍然失败，请检查 OpenClaw 里配置的 MiniMax API Key 是否属于刚充值的账号。"
      ].join("\n");
    }

    if (rule?.id === "volcengine-ark") {
      return [
        "⚠️ 火山引擎方舟/豆包模型服务返回了账单错误，账号可能欠费、余额不足，或当前 API Key 不可用。",
        "",
        `当前模型：${model || "火山引擎方舟"}`,
        `处理方式：${rule.action}`,
        `API 管理入口：${rule.billingUrl}`,
        "",
        "如果确认账号已恢复，请检查 OpenClaw 里配置的 API Key 是否来自这个可用账号。"
      ].join("\n");
    }

    const providerName = provider || "模型服务商";
    return [
      `⚠️ ${providerName} 模型服务返回了账单错误，API Key 可能余额不足、账号欠费或额度用尽。`,
      "",
      "处理方式：请进入对应模型服务商的控制台充值或续费，然后回到当前对话重试；也可以在 OpenClaw 中切换到可用的 API Key。"
    ].join("\n");
  }

  return null;
}
