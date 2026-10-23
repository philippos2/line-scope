// Helper for the maintained scenario1 runner; no environment creation or writes.
import { readFileSync } from "node:fs";
import { URL } from "node:url";
import { expect } from "playwright/test";

export const h6Fixture = JSON.parse(
  readFileSync(
    new URL("./fixtures/h6-questions.json", import.meta.url),
    "utf8",
  ),
);
export function h6AllowedRequest(body) {
  if (!body || typeof body.message !== "string") return false;
  if (
    Object.keys(body).some(
      (key) =>
        !["message", "context_id", "as_of", "read_confirmation"].includes(key),
    )
  )
    return false;
  if (
    body.read_confirmation !== undefined &&
    !["ACCEPT", "REJECT"].includes(body.read_confirmation)
  )
    return false;
  const question = body.message.replace(
    /^調査対象の設備コードは[^\n]+です。\n/u,
    "",
  );
  return h6Fixture.cases.some(
    (row) => row.expected !== "SEARCH" && row.question === question,
  );
}

export async function acceptReadScope(page, question) {
  const response = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith("/agent") &&
      r.request().postDataJSON()?.read_confirmation === "ACCEPT" &&
      r.request().postDataJSON()?.message?.endsWith(question),
    { timeout: 135000 },
  );
  await page
    .getByRole("button", { name: "この範囲を調べる", exact: true })
    .click();
  const actual = await response;
  expect(actual.status()).toBe(200);
  const body = await actual.json();
  expect(body.data.read_clarification?.status).toBe("ACCEPTED");
  expect(body.data.needs_input).toBe(false);
  expect(body.data.update_request_id).toBeUndefined();
  return body;
}

function inspectFacts(body) {
  const tools = body.data.tool_results;
  const sections = body.data.answer_sections;
  expect(sections?.version).toBe(1);
  expect(body.data.update_request_id).toBeUndefined();
  for (const fact of sections.facts) {
    expect(fact.references.length).toBeGreaterThan(0);
    for (const ref of fact.references)
      expect(tools.some((tool) => tool.tool_call_id === ref)).toBe(true);
  }
}
function inspectState(body, row) {
  if (!row.expected_state) return;
  const tools = body.data.tool_results;
  const states = tools.filter((tool) => tool.tool === "get_equipment_state");
  expect(states).toHaveLength(1);
  expect(states[0].data.state_code).toBe(row.expected_state);
  const equipment = tools.flatMap((tool) =>
    tool.tool === "search_equipment" ? tool.data.items : [],
  );
  expect(
    equipment.some(
      (item) =>
        item.equipment_code === row.equipment_code &&
        item.equipment_id === states[0].data.equipment_id,
    ),
  ).toBe(true);
  expect(
    body.data.answer_sections.facts.some((fact) =>
      fact.references.includes(states[0].tool_call_id),
    ),
  ).toBe(true);
}

export async function runH6(page, base, token, report) {
  const start = Date.parse(process.env.LINESCOPE_BROWSER_H6_WINDOW_START ?? "");
  const end = Date.parse(process.env.LINESCOPE_BROWSER_H6_WINDOW_END ?? "");
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    start >= end ||
    Date.now() < start ||
    Date.now() >= end
  )
    throw new Error(
      "An explicitly approved current H6 time window is required",
    );
  const cases = h6Fixture.cases;
  expect(cases).toHaveLength(20);
  expect(new Set(cases.map((row) => row.id)).size).toBe(20);
  expect(cases.reduce((sum, row) => sum + row.repeat, 0)).toBe(44);
  const identityTools = new Set([
    "search_equipment",
    "get_equipment",
    "get_process",
    "get_product",
    "get_production_operation",
    "get_infrastructure_resource",
  ]);
  report.h6_cases = [];
  report.model_call_count = null; // Obtain from server llm.call.completed, not HTTP count.
  let timeoutStreak = 0;
  await page.goto(base);
  await page.getByLabel("Bearer token").fill(token);
  await page.getByRole("button", { name: "接続する", exact: true }).click();
  await page.getByLabel("設備名・コード", { exact: true }).fill("M-204");
  await page.getByRole("button", { name: "検索", exact: true }).click();
  const origin = page
    .locator(".equipment-search-panel > .equipment-result")
    .filter({ hasText: "M-204" });
  await expect(origin).toHaveCount(1);
  await origin.click();
  await page.getByRole("tab", { name: "質問する", exact: true }).click();
  for (const row of cases) {
    for (let repeat = 1; repeat <= row.repeat; repeat++) {
      // Reserve two response deadlines and UI time. Never silently run past the window.
      if (Date.now() + 270000 >= end)
        throw new Error("H6 time window has insufficient remaining time");
      const sample = { ...row, repeat, elapsed_ms: null };
      report.h6_cases.push(sample);
      const began = Date.now();
      try {
        if (row.expected === "SEARCH") {
          await page
            .getByLabel("設備名・コード", { exact: true })
            .fill(row.question);
          await page.getByRole("button", { name: "検索", exact: true }).click();
          await expect(
            page
              .locator(".equipment-search-panel > .equipment-result")
              .filter({ hasText: row.equipment_code }),
          ).toHaveCount(1);
          sample.outcome = "SEARCH";
          sample.pass = true;
          continue;
        }
        await page
          .getByLabel("関係や影響について質問する", { exact: true })
          .fill(row.question);
        const pending = page.waitForResponse(
          (r) =>
            new URL(r.url()).pathname.endsWith("/agent") &&
            !r.request().postDataJSON()?.read_confirmation &&
            r.request().postDataJSON()?.message?.endsWith(row.question),
          { timeout: 135000 },
        );
        await page.getByRole("button", { name: "送信", exact: true }).click();
        const response = await pending;
        const body = await response.json();
        sample.response = body;
        sample.outcome = body.data?.answer_sections?.read_outcome ?? "ERROR";
        const limited = body.errors?.some(
          (error) => error.code === "AGENT_LIMIT_REACHED",
        );
        timeoutStreak = limited ? timeoutStreak + 1 : 0;
        expect(response.status()).toBe(200);
        inspectFacts(body);
        expect(sample.outcome).toBe(row.expected);
        if (
          ["UNSUPPORTED", "TARGET_AMBIGUOUS", "CONFIRM"].includes(row.expected)
        ) {
          expect(
            body.data.tool_results.every((tool) =>
              identityTools.has(tool.tool),
            ),
          ).toBe(true);
          expect(
            body.data.answer_sections.facts.every(
              (fact) =>
                fact.predicate === "equipment.identity" ||
                (row.expected === "TARGET_AMBIGUOUS" &&
                  fact.predicate === "equipment.identity_candidate"),
            ),
          ).toBe(true);
        }
        if (row.expected === "CONFIRM") {
          expect(body.data.read_clarification?.status).toBe("PENDING");
          expect(body.data.answer_sections.facts).toHaveLength(0);
          expect(body.data.read_clarification.targets.join(" ")).toContain(
            row.equipment_code,
          );
          expect(body.data.read_clarification.original_question).toBe(
            row.question,
          );
          const confirmed = await acceptReadScope(page, row.question);
          sample.confirmed_response = confirmed;
          inspectFacts(confirmed);
          inspectState(confirmed, row);
          expect(confirmed.data.answer_sections.read_outcome).toBe(
            "EXPLICIT_READ",
          );
        } else if (row.expected === "AUTO") {
          expect(body.data.read_clarification).toBeUndefined();
          inspectState(body, row);
          if (row.expected_tool)
            expect(
              body.data.tool_results.some(
                (tool) => tool.tool === row.expected_tool,
              ),
            ).toBe(true);
        } else if (row.expected === "TARGET_AMBIGUOUS") {
          expect(body.data.needs_input).toBe(true);
        }
        await expect(
          page.getByRole("button", { name: "送信", exact: true }),
        ).toBeEnabled();
        expect(
          await page.locator(".question-response").innerText(),
        ).not.toMatch(/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/i);
        sample.pass = true;
      } catch (error) {
        if (
          !sample.response &&
          /timeout|timed out/i.test(error.name + " " + error.message)
        )
          timeoutStreak++;
        sample.failure = error.message;
        sample.pass = false;
      } finally {
        sample.elapsed_ms = Date.now() - began;
      }
      if (timeoutStreak >= 2)
        throw new Error("Repeated response deadlines: H6 execution stopped");
    }
  }
  const questions = report.h6_cases.filter((row) => row.expected !== "SEARCH");
  const ratio = (numerator, denominator) => ({
    numerator,
    denominator,
    rate: denominator ? numerator / denominator : null,
  });
  report.h6_metrics = {
    false_acceptance_rate: ratio(
      questions.filter(
        (row) => row.expected === "UNSUPPORTED" && row.outcome === "AUTO",
      ).length,
      questions.filter((row) => row.expected === "UNSUPPORTED").length,
    ),
    false_rejection_rate: ratio(
      questions.filter(
        (row) => row.expected === "AUTO" && row.outcome !== "AUTO",
      ).length,
      questions.filter((row) => row.expected === "AUTO").length,
    ),
    confirmation_rate: ratio(
      questions.filter((row) => row.outcome === "CONFIRM").length,
      questions.length,
    ),
    planned: 44,
    completed: report.h6_cases.length,
    passed: report.h6_cases.filter((row) => row.pass).length,
    failed: report.h6_cases.filter((row) => !row.pass).length,
    question_runs: questions.length,
    confirmations: questions.filter((row) => row.outcome === "CONFIRM").length,
    route_mismatches: questions.filter((row) => row.outcome !== row.expected)
      .length,
    unsupported_auto_accepts: questions.filter(
      (row) => row.expected === "UNSUPPORTED" && row.outcome === "AUTO",
    ).length,
    answerable_route_misses: questions.filter(
      (row) => row.expected === "AUTO" && row.outcome !== "AUTO",
    ).length,
  };
  expect(report.h6_cases).toHaveLength(44);
  expect(report.h6_cases.every((row) => row.pass)).toBe(true);
}
