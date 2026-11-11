// SPDX-License-Identifier: AGPL-3.0-only
import { isAxiosError } from "axios";
import { API_BASE_URL } from "@plane/constants";
import { APIService } from "@/services/api.service";
import type { Page } from "./types";

class QualityService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }
  async read<T>(url: string): Promise<T> {
    return (await this.get(url)).data;
  }
  async write<T>(url: string, data: object, method: "post" | "patch" | "delete" = "post"): Promise<T> {
    if (method === "delete") return (await this.delete(url)).data;
    return (await this[method](url, data)).data;
  }
  async blob(url: string): Promise<Blob> {
    return (await this.get(url, {}, { responseType: "blob" })).data;
  }
  async download(url: string, filename: string): Promise<void> {
    const response = await this.get(url, {}, { responseType: "blob" }).catch(async (error: unknown) => {
      if (isAxiosError(error) && error.response?.data instanceof Blob) {
        try {
          error.response.data = JSON.parse(await error.response.data.text());
        } catch {
          // Keep the original response when the server did not return a JSON error.
        }
      }
      throw error;
    });
    const objectUrl = URL.createObjectURL(response.data);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(objectUrl);
  }
  async all<T>(url: string): Promise<T[]> {
    const first = await this.read<Page<T>>(`${url}?per_page=100&page=1`);
    const pages = Array.from({ length: Math.max(0, Math.ceil(first.count / 100) - 1) }, (_, index) => index + 2);
    const rest = await Promise.all(pages.map((page) => this.read<Page<T>>(`${url}?per_page=100&page=${page}`)));
    return [...first.results, ...rest.flatMap((page) => page.results)];
  }
}
export const qualityApi = new QualityService();
export function errorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    if (error.response?.status === 403) return "您没有当前项目的操作权限，请联系项目经理。";
    const data: unknown = error.response?.data;
    if (data && typeof data === "object") {
      const values = Object.values(data).flat();
      const message = values.filter((v): v is string => typeof v === "string").join("；");
      if (message) return message;
    }
    if (error.response?.status === 409) return "数据已变更或提交编号重复，请刷新后重试；已填写的内容仍保留。";
  }
  if (error instanceof Error && !isAxiosError(error)) return error.message;
  return "操作失败，请检查网络后重试。";
}

/** Keep original storage names while making generated evidence recognizable. */
export function attachmentDisplayName(name: string): string {
  return name
    .replace(/^feedback-([0-9a-f-]{36})\.json$/i, "feedback-version-$1.json")
    .replace(/^daq-diagnostics-([0-9a-f-]{36})\.zip$/i, "daq-diagnostic-logs-$1.zip");
}
