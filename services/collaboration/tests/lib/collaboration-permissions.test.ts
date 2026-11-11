import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ currentUser: vi.fn(), fetchDetails: vi.fn() }));
vi.mock("@/services/user.service", () => ({
  UserService: class {
    currentUser = mocks.currentUser;
  },
}));
vi.mock("@/services/page/handler", () => ({ getPageService: () => ({ fetchDetails: mocks.fetchDetails }) }));
vi.mock("@plane/logger", () => ({ logger: { error: vi.fn() } }));
import { onAuthenticate, beforeHandleMessage } from "@/lib/auth";
const attempt = () => ({
  requestHeaders: { cookie: "test-only-cookie" },
  requestParameters: new URLSearchParams({ documentType: "project_page", workspaceSlug: "w", projectId: "p" }),
  context: {} as any,
  token: JSON.stringify({ id: "u" }),
  documentName: "doc",
  connection: { readOnly: false },
});
describe("collaborative document authorization", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.currentUser.mockResolvedValue({ id: "u", display_name: "test" });
  });
  it("checks page authorization even when a document is already cached", async () => {
    mocks.fetchDetails.mockRejectedValue(new Error("Forbidden"));
    await expect(onAuthenticate(attempt())).rejects.toThrow();
  });
  it.each([
    { can_write: false },
    {},
    { can_write: true, is_locked: true },
    { can_write: true, archived_at: "2026/11/08" },
  ])("readonly or unavailable edit capability disables collaborative writes: %j", async (page) => {
    mocks.fetchDetails.mockResolvedValue(page);
    const payload = attempt();
    await onAuthenticate(payload);
    expect(payload.connection.readOnly).toBe(true);
  });
  it("allows authorized collaborative writes", async () => {
    mocks.fetchDetails.mockResolvedValue({ can_write: true, is_locked: false, archived_at: null });
    const payload = attempt();
    await onAuthenticate(payload);
    expect(payload.connection.readOnly).toBe(false);
  });
  it("revoked access closes a previously authorized connection before another message", async () => {
    mocks.fetchDetails.mockResolvedValueOnce({ can_write: true }).mockRejectedValueOnce(new Error("Forbidden"));
    const payload = attempt();
    await onAuthenticate(payload);
    await expect(beforeHandleMessage(payload)).rejects.toThrow("Forbidden");
  });
  it("downgraded duty makes an existing connection readonly before another message", async () => {
    mocks.fetchDetails.mockResolvedValueOnce({ can_write: true }).mockResolvedValueOnce({ can_write: false });
    const payload = attempt();
    await onAuthenticate(payload);
    await beforeHandleMessage(payload);
    expect(payload.connection.readOnly).toBe(true);
  });
});
