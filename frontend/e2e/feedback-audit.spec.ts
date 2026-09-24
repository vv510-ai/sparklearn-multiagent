import { test, expect } from "@playwright/test";

test("注册输入框使用完整焦点边框，键盘焦点保持可见", async ({ page }, info) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "创建账户" }).click();
  const name = page.getByPlaceholder("怎么称呼你");
  await name.focus();
  const styles = await name.evaluate(el => {
    const input = getComputedStyle(el);
    const shell = getComputedStyle(el.closest(".auth-input-shell")!);
    return { inputOutline: input.outlineStyle, border: shell.borderColor, outline: shell.outlineStyle, width: shell.outlineWidth };
  });
  expect(styles.inputOutline).toBe("none");
  expect(styles.outline).toBe("solid");
  expect(Number.parseFloat(styles.width)).toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: info.outputPath("auth-focus.png") });
  await page.keyboard.press("Tab");
  await expect(page.getByPlaceholder("you@example.com")).toBeFocused();
});
