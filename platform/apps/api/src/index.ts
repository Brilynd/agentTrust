import "dotenv/config";

import http from "node:http";

import { createApp } from "./app";
import { logger } from "./lib/logger";
import { initSocket } from "./socket";

const port = Number(process.env.PORT || 3200);
const app = createApp();
const server = http.createServer(app);

initSocket(server);

server.listen(port, () => {
  logger.info({ port }, "agenttrust platform api listening");
});
