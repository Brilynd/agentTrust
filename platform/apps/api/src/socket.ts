import type { Server as HttpServer } from "node:http";

import { Server } from "socket.io";

import { logger } from "./lib/logger";

let io: Server | undefined;

export function initSocket(server: HttpServer) {
  io = new Server(server, {
    cors: {
      origin: process.env.DASHBOARD_ORIGIN || "http://localhost:3001",
      credentials: true
    }
  });

  io.on("connection", (socket) => {
    logger.info({ socketId: socket.id }, "dashboard connected");

    socket.on("platform:event", ({ channel, payload }) => {
      io?.emit(channel, payload);
    });
  });

  return io;
}

export function emitPlatformEvent(channel: string, payload: unknown) {
  io?.emit(channel, payload);
}
