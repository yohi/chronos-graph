import { test, expect } from '@playwright/test'

/**
 * Dashboard E2E tests — design doc §7.2 happy-path.
 *
 * These tests run against a live Vite dev server proxying to FastAPI.
 * For CI, set E2E_BASE_URL to the deployed dashboard URL and ensure
 * the MCP server has been started at least once to initialise the DB.
 *
 * Note: The tests use route mocking (page.route) so they work without
 * a running FastAPI backend, making them suitable for PR-level checks.
 */

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

const MOCK_STATS = {
  activeCount: 42,
  archivedCount: 8,
  totalCount: 50,
  edgeCount: 123,
  projectCount: 3,
  projects: ['proj-a', 'proj-b', 'proj-c'],
}

const MOCK_GRAPH = {
  elements: {
    nodes: [
      {
        data: {
          id: 'node-1',
          label: 'Test memory about server configuration',
          memoryType: 'episodic',
          importance: 0.8,
          project: 'proj-a',
        },
      },
      {
        data: {
          id: 'node-2',
          label: 'Knowledge about Python best practices',
          memoryType: 'semantic',
          importance: 0.6,
          project: 'proj-b',
        },
      },
    ],
    edges: [
      {
        data: {
          id: 'node-1-node-2-RELATED',
          source: 'node-1',
          target: 'node-2',
          edgeType: 'RELATED',
        },
      },
    ],
  },
  totalNodes: 2,
  totalEdges: 1,
  returnedNodes: 2,
}

// ---------------------------------------------------------------------------
// Test: Dashboard page — StatCard renders API values (design doc §7.2 case 1)
// ---------------------------------------------------------------------------

test.describe('Dashboard page', () => {
  test.beforeEach(async ({ page }) => {
    // Mock /api/stats/summary to avoid requiring a live backend
    await page.route('**/api/stats/summary', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_STATS),
      }),
    )
  })

  test('displays StatCards with values from /api/stats/summary', async ({ page }) => {
    await page.goto('/')

    // Wait for loading to complete
    await expect(page.getByText('System Overview')).toBeVisible()

    // Verify stat values are rendered
    await expect(page.getByText('42')).toBeVisible()   // activeCount
    await expect(page.getByText('8')).toBeVisible()    // archivedCount
    await expect(page.getByText('50')).toBeVisible()   // totalCount
    await expect(page.getByText('123')).toBeVisible()  // edgeCount

    // Verify project badges
    await expect(page.getByText('proj-a')).toBeVisible()
    await expect(page.getByText('proj-b')).toBeVisible()
    await expect(page.getByText('proj-c')).toBeVisible()
  })

  test('shows error state when API fails', async ({ page }) => {
    // Override mock to return an error
    await page.route('**/api/stats/summary', (route) =>
      route.fulfill({ status: 503, body: 'Service Unavailable' }),
    )

    await page.goto('/')
    await expect(page.getByText(/Error/)).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// Test: NetworkView — graph renders (design doc §7.2 case 2)
// ---------------------------------------------------------------------------

test.describe('NetworkView page', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/graph/layout**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_GRAPH),
      }),
    )
  })

  test('navigates to /network and renders the Cytoscape container', async ({ page }) => {
    await page.goto('/network')

    await expect(page.getByRole('heading', { name: 'Network View' })).toBeVisible()

    // Cytoscape canvas container should be present (design doc §5.2)
    const container = page.getByTestId('network-graph')
    await expect(container).toBeVisible()
  })

  test('shows truncation warning when totalNodes > returnedNodes', async ({ page }) => {
    // Override with truncated response
    await page.route('**/api/graph/layout**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...MOCK_GRAPH,
          totalNodes: 500,
          returnedNodes: 2,
        }),
      }),
    )

    await page.goto('/network')

    // Truncation warning banner should appear (design doc §4.3)
    await expect(page.getByText(/Showing 2 of 500 memories/)).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// Test: SPA routing — direct URL access works (design doc §3.5)
// ---------------------------------------------------------------------------

test.describe('SPA routing', () => {
  test('direct navigation to /network returns 200', async ({ page }) => {
    const response = await page.goto('/network')
    expect(response?.status()).toBeLessThan(400)
    await expect(page.getByRole('heading', { name: 'Network View' })).toBeVisible()
  })

  test('direct navigation to /logs returns 200', async ({ page }) => {
    const response = await page.goto('/logs')
    expect(response?.status()).toBeLessThan(400)
  })

  test('direct navigation to /settings returns 200', async ({ page }) => {
    const response = await page.goto('/settings')
    expect(response?.status()).toBeLessThan(400)
  })
})
