/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { RequestHandler } from "express";
import { logger } from "./config";

export const loggerMiddleware: RequestHandler = (req, res, next) => {
  const started = Date.now();
  res.on("finish", () => {
    logger.info("HTTP request", {
      method: req.method,
      path: /^\/(?:auth|reset-password)(?:\/|$)/.test(req.path) ? "[authentication]" : req.path.slice(0, 2048),
      statusCode: res.statusCode,
      durationMs: Math.max(0, Date.now() - started),
    });
  });
  next();
};
