// Main Express Server
// Entry point for AgentTrust backend API

require('dotenv').config();
const express = require('express');
const http = require('http');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const mongoSanitize = require('express-mongo-sanitize');
const hpp = require('hpp');
const morgan = require('morgan');

const app = express();
const PORT = process.env.PORT || 3000;
const server = http.createServer(app);

// Security Middleware
// Helmet - Set security HTTP headers
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", "data:", "https:"],
    },
  },
  crossOriginEmbedderPolicy: false
}));

// CORS Configuration
const corsOptions = {
  origin: process.env.CORS_ORIGIN?.split(',') || ['http://localhost:3000', 'http://localhost:3001'],
  credentials: true,
  optionsSuccessStatus: 200,
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization']
};
app.use(cors(corsOptions));

// Rate Limiting
const limiter = rateLimit({
  windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS) || 15 * 60 * 1000,
  max: parseInt(process.env.RATE_LIMIT_MAX_REQUESTS) || 10000,
  message: {
    success: false,
    error: 'Too many requests from this IP, please try again later.'
  },
  standardHeaders: true,
  legacyHeaders: false,
});
app.use('/api/', limiter);

// Body parsing middleware (with size limits)
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// Data sanitization - prevent NoSQL injection
app.use(mongoSanitize());

// Prevent HTTP Parameter Pollution
app.use(hpp());

// Request logging
if (process.env.NODE_ENV === 'development') {
  app.use(morgan('dev'));
} else {
  app.use(morgan('combined'));
}

// Additional security middleware
const { requestId, securityHeaders, validateInput } = require('./middleware/security');
app.use(requestId);
app.use(securityHeaders);
app.use(validateInput);

// Static files (login page for extension auto sign-in)
const path = require('path');
app.use(express.static(path.join(__dirname, '..', 'public')));

// Routes
app.use('/api/actions', require('./routes/actions'));
app.use('/api', require('./routes/agent-platform'));
app.use('/api/auth', require('./routes/auth'));
app.use('/api/users', require('./routes/users'));
app.use('/api/sessions', require('./routes/sessions'));
app.use('/api/policies', require('./routes/policies'));
app.use('/api/audit', require('./routes/audit'));
app.use('/api/prompts', require('./routes/prompts'));
app.use('/api/commands', require('./routes/commands'));
app.use('/api/approvals', require('./routes/approvals'));
app.use('/api/credentials', require('./routes/credentials'));
app.use('/api/sensitive-data', require('./routes/sensitive-data'));
app.use('/api/token-vault', require('./routes/token-vault'));
app.use('/api/external', require('./routes/external-api'));
app.use('/api/routines', require('./routes/routines'));

const { initPlatformSocket } = require('./services/platformSocket');
initPlatformSocket(server);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Error:', err);
  res.status(err.status || 500).json({
    error: err.message || 'Internal server error'
  });
});

// Start server
server.listen(PORT, async () => {
  console.log(`AgentTrust backend server running on port ${PORT}`);
  try {
    await require('./services/workerManager').recoverWorkers();
  } catch (error) {
    console.error('Failed to recover backend-managed workers:', error);
  }
});
