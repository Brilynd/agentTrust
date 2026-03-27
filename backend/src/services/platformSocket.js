const { Server } = require('socket.io');

let io;

function initPlatformSocket(server) {
  io = new Server(server, {
    cors: {
      origin: process.env.DASHBOARD_ORIGIN || process.env.CORS_ORIGIN?.split(',') || ['http://localhost:3001'],
      credentials: true
    }
  });

  io.on('connection', (socket) => {
    console.log(`Platform dashboard connected: ${socket.id}`);
    socket.on('platform:event', ({ channel, payload }) => {
      if (channel) {
        io.emit(channel, payload);
      }
    });
  });

  return io;
}

function emitPlatformEvent(channel, payload) {
  if (io) {
    io.emit(channel, payload);
  }
}

module.exports = {
  initPlatformSocket,
  emitPlatformEvent
};
