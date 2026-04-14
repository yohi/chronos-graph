import { test, expect } from '@playwright/test';

test('dashboard loads and displays summary', async ({ page }) => {
  // Wait for the app to load
  await page.goto('/');

  // Verify main title is visible
  await expect(page.locator('text=System Overview')).toBeVisible();

  // Verify stats cards are present
  await expect(page.locator('text=Active Memories')).toBeVisible();
});
