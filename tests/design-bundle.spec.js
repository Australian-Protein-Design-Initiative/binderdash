// @ts-check
const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

/** List the member names of a zip using python3's stdlib, so no JS zip dependency. */
function zipMembers(zipPath) {
    const out = execFileSync('python3', [
        '-c',
        'import sys, zipfile; print("\\n".join(zipfile.ZipFile(sys.argv[1]).namelist()))',
        zipPath,
    ]);
    return out.toString().split('\n').filter(Boolean);
}

/** Read one member of a zip as text. */
function zipRead(zipPath, member) {
    return execFileSync('python3', [
        '-c',
        'import sys, zipfile; sys.stdout.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]).decode())',
        zipPath,
        member,
    ]).toString();
}

/**
 * Select a run, then mark the top few designs, so the bundle covers a handful of rows
 * rather than every design in the run - which is how the feature is actually used, and
 * keeps the test fast.
 */
async function selectRunAndTopDesigns(page, n = 3) {
    await page.getByRole('tab', { name: 'Select Runs' }).click();
    const runRows = page.locator('[role="tabpanel"]:visible tbody tr');
    await expect(runRows.first()).toBeVisible({ timeout: 60000 });
    await runRows.first().locator('input[type="checkbox"]').first().check();

    await page.getByRole('tab', { name: 'Designs', exact: true }).click();
    const panel = page.locator('[role="tabpanel"]:visible');
    await expect(panel.locator('.p-datatable-tbody tr').first()).toBeVisible({ timeout: 60000 });

    // Tick the first few row checkboxes. getRowsToExport() prefers the explicit
    // selection, so the bundle covers just these rows.
    const rows = panel.locator('.p-datatable-tbody tr');
    for (let i = 0; i < n; i++) {
        await rows.nth(i).locator('input[type="checkbox"]').first().check();
    }
    return panel;
}

test.describe('Design bundle download', () => {
    test.setTimeout(120000);

    test('the default Designs action downloads a zip carrying tables, structures and session state', async ({ page }) => {
        await page.goto('/');
        const designsPanel = await selectRunAndTopDesigns(page, 3);

        // Sort the table, so the session state has something non-default to record.
        const sortable = designsPanel.locator('th[aria-sort]').nth(1);
        await expect(sortable).toBeVisible({ timeout: 30000 });
        await sortable.click();
        await expect(sortable).toHaveAttribute('aria-sort', /ascending|descending/);

        const [download] = await Promise.all([
            page.waitForEvent('download', { timeout: 60000 }),
            page.getByRole('button', { name: 'Download Design Bundle (zip)' }).first().click(),
        ]);

        expect(download.suggestedFilename()).toMatch(/\.zip$/);
        const folder = download.suggestedFilename().replace(/\.zip$/i, '');

        const zipPath = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bd-bundle-')), 'bundle.zip');
        await download.saveAs(zipPath);

        const members = zipMembers(zipPath);
        // One folder, named after the download, so unzip does not scatter files.
        expect(members.every((m) => m.startsWith(`${folder}/`))).toBe(true);
        expect(members).toContain(`${folder}/manifest.json`);
        expect(members).toContain(`${folder}/designs.tsv`);
        expect(members).toContain(`${folder}/binderdash_session.json`);
        expect(members).toContain(`${folder}/README.txt`);
        // The CSV variant stays a separate dropdown item; it is not in the bundle.
        expect(members).not.toContain(`${folder}/designs.csv`);
        expect(members.some((m) => m.startsWith(`${folder}/schemas/`))).toBe(true);

        const manifest = JSON.parse(zipRead(zipPath, `${folder}/manifest.json`));
        expect(manifest.bundle_kind).toBe('designs');
        expect(manifest.build.app_version).toBeTruthy();
        expect(manifest.coverage.designs).toBeGreaterThan(0);
        // Every member but the manifest itself is inventoried with a digest.
        for (const entry of manifest.files) {
            expect(entry.sha256).toMatch(/^[0-9a-f]{64}$/);
        }

        const session = JSON.parse(zipRead(zipPath, `${folder}/binderdash_session.json`));
        expect(session.kind).toBe('binderdash.session');
        expect(session.captured).toBe(true);
        expect(session.run_ids.length).toBeGreaterThan(0);
        expect(session.sort.length).toBeGreaterThan(0);

        fs.rmSync(path.dirname(zipPath), { recursive: true, force: true });
    });

    test('a session JSON from a bundle restores the run selection and table sort', async ({ page }) => {
        await page.goto('/');
        const designsPanel = await selectRunAndTopDesigns(page, 3);

        const sortable = designsPanel.locator('th[aria-sort]').nth(1);
        await expect(sortable).toBeVisible({ timeout: 30000 });
        await sortable.click();
        const sortedColumn = (await sortable.innerText()).trim();

        const [download] = await Promise.all([
            page.waitForEvent('download', { timeout: 60000 }),
            page.getByRole('button', { name: 'Download Design Bundle (zip)' }).first().click(),
        ]);
        const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bd-restore-'));
        const zipPath = path.join(tmpDir, 'bundle.zip');
        await download.saveAs(zipPath);

        const sessionPath = path.join(tmpDir, 'binderdash_session.json');
        const folder = download.suggestedFilename().replace(/\.zip$/i, '');
        const sessionText = zipRead(zipPath, `${folder}/binderdash_session.json`);
        fs.writeFileSync(sessionPath, sessionText);
        const expected = JSON.parse(sessionText);

        // Wipe the persisted UI state the way a fresh browser would see it, then reload.
        await page.evaluate(async () => {
            const dbs = (await indexedDB.databases?.()) ?? [];
            await Promise.all(
                dbs.map(
                    (d) =>
                        new Promise((resolve) => {
                            const req = indexedDB.deleteDatabase(d.name);
                            req.onsuccess = req.onerror = req.onblocked = () => resolve(undefined);
                        })
                )
            );
            localStorage.clear();
        });
        await page.reload();

        await page.getByRole('tab', { name: 'Designs', exact: true }).click();
        await expect(page.locator('[role="tabpanel"]:visible')).toContainText('No Designs Found', {
            timeout: 30000,
        });

        await page.getByRole('button', { name: 'Restore session' }).click();
        await page.locator('input[type="file"]').setInputFiles(sessionPath);

        // The dialog reports per-section outcomes; the run selection and sort are the
        // load-bearing ones for this round trip.
        const dialog = page.getByRole('dialog');
        await expect(dialog.getByText('Runs', { exact: true })).toBeVisible({ timeout: 30000 });
        await expect(dialog.getByText('Table sort', { exact: true })).toBeVisible();
        await page.locator('.p-dialog-footer').getByRole('button', { name: 'Close' }).click();

        await page.getByRole('tab', { name: 'Designs', exact: true }).click();
        const restoredPanel = page.locator('[role="tabpanel"]:visible');
        await expect(restoredPanel.locator('.p-datatable-tbody tr').first()).toBeVisible({
            timeout: 30000,
        });

        const restoredSort = restoredPanel.locator('th[aria-sort="ascending"], th[aria-sort="descending"]');
        await expect(restoredSort.first()).toContainText(sortedColumn.split('\n')[0]);
        expect(expected.sort[0].field).toBeTruthy();

        fs.rmSync(tmpDir, { recursive: true, force: true });
    });

    test('a disabled filter is still disabled after a session restore', async ({ page }) => {
        await page.goto('/');
        await selectRunAndTopDesigns(page, 3);

        // Add a hard filter, then switch it off. `enabled` is a UI-only flag that the
        // backend never sees, so it only survives the round trip via the session JSON.
        await page.getByRole('tab', { name: 'Filtering' }).click();
        const filtering = page.locator('[role="tabpanel"]:visible');
        await filtering.getByRole('button', { name: 'Add filter' }).click();
        const toggle = filtering.getByLabel('Enable filter').first();
        await expect(toggle).toBeVisible({ timeout: 30000 });
        await toggle.click();
        await expect(toggle).toHaveAttribute('aria-checked', 'false');

        await page.getByRole('tab', { name: 'Designs', exact: true }).click();
        const [download] = await Promise.all([
            page.waitForEvent('download', { timeout: 60000 }),
            page.getByRole('button', { name: 'Download Design Bundle (zip)' }).first().click(),
        ]);
        const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bd-enabled-'));
        const zipPath = path.join(tmpDir, 'bundle.zip');
        await download.saveAs(zipPath);

        const folder = download.suggestedFilename().replace(/\.zip$/i, '');
        const sessionText = zipRead(zipPath, `${folder}/binderdash_session.json`);
        const sessionPath = path.join(tmpDir, 'binderdash_session.json');
        fs.writeFileSync(sessionPath, sessionText);

        // The capture side must record the flag...
        const captured = JSON.parse(sessionText);
        expect(captured.filtering.filters[0].enabled).toBe(false);

        await page.evaluate(async () => {
            const dbs = (await indexedDB.databases?.()) ?? [];
            await Promise.all(
                dbs.map(
                    (d) =>
                        new Promise((resolve) => {
                            const req = indexedDB.deleteDatabase(d.name);
                            req.onsuccess = req.onerror = req.onblocked = () => resolve(undefined);
                        })
                )
            );
            localStorage.clear();
        });
        await page.reload();

        await page.getByRole('button', { name: 'Restore session' }).click();
        await page.locator('input[type="file"]').setInputFiles(sessionPath);
        await expect(page.getByRole('dialog').getByText('Filters and ranking', { exact: true })).toBeVisible({
            timeout: 30000,
        });
        await page.locator('.p-dialog-footer').getByRole('button', { name: 'Close' }).click();

        // ...and the restore side must honour it, rather than defaulting every row on.
        await page.getByRole('tab', { name: 'Filtering' }).click();
        const restored = page.locator('[role="tabpanel"]:visible').getByLabel('Enable filter').first();
        await expect(restored).toBeVisible({ timeout: 30000 });
        await expect(restored).toHaveAttribute('aria-checked', 'false');

        fs.rmSync(tmpDir, { recursive: true, force: true });
    });
});
