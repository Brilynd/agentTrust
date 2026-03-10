// CloudWatch Logging Service
// Sends structured records to AWS CloudWatch Logs alongside RDS writes

const {
  CloudWatchLogsClient,
  CreateLogGroupCommand,
  CreateLogStreamCommand,
  PutLogEventsCommand,
  DescribeLogStreamsCommand
} = require('@aws-sdk/client-cloudwatch-logs');

require('dotenv').config();

const LOG_GROUP = process.env.CLOUDWATCH_LOG_GROUP || 'agentTrust';
const AWS_REGION = process.env.AWS_REGION || 'us-east-2';
const ENABLED = process.env.CLOUDWATCH_ENABLED !== 'false'; // enabled by default

let client = null;
let initialised = false;
let sequenceTokens = {}; // streamName -> sequenceToken

// Pre-defined log streams (one per record type)
const STREAMS = {
  actions: 'actions',
  sessions: 'sessions',
  prompts: 'prompts',
  users: 'users',
  credentials: 'credentials',
  routines: 'routines',
  connections: 'connections'
};

function getClient() {
  if (!client) {
    const config = { region: AWS_REGION };

    // Allow explicit credentials from env, otherwise falls back to
    // default credential chain (EC2 role, env vars, ~/.aws, etc.)
    if (process.env.AWS_ACCESS_KEY_ID && process.env.AWS_SECRET_ACCESS_KEY) {
      config.credentials = {
        accessKeyId: process.env.AWS_ACCESS_KEY_ID,
        secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY
      };
    }

    client = new CloudWatchLogsClient(config);
  }
  return client;
}

async function ensureLogGroupAndStreams() {
  if (initialised) return;

  const cw = getClient();

  // Create log group (ignore if already exists)
  try {
    await cw.send(new CreateLogGroupCommand({ logGroupName: LOG_GROUP }));
    console.log(`[CloudWatch] Created log group: ${LOG_GROUP}`);
  } catch (err) {
    if (err.name !== 'ResourceAlreadyExistsException') {
      console.error('[CloudWatch] Error creating log group:', err.message);
    }
  }

  // Create each log stream
  for (const stream of Object.values(STREAMS)) {
    try {
      await cw.send(new CreateLogStreamCommand({
        logGroupName: LOG_GROUP,
        logStreamName: stream
      }));
    } catch (err) {
      if (err.name !== 'ResourceAlreadyExistsException') {
        console.error(`[CloudWatch] Error creating stream ${stream}:`, err.message);
      }
    }
  }

  initialised = true;
}

async function getSequenceToken(streamName) {
  if (sequenceTokens[streamName]) return sequenceTokens[streamName];

  const cw = getClient();
  try {
    const res = await cw.send(new DescribeLogStreamsCommand({
      logGroupName: LOG_GROUP,
      logStreamNamePrefix: streamName,
      limit: 1
    }));
    const token = res.logStreams?.[0]?.uploadSequenceToken || null;
    sequenceTokens[streamName] = token;
    return token;
  } catch {
    return null;
  }
}

/**
 * Send a structured record to CloudWatch Logs.
 * This is fire-and-forget — failures are logged but never block the caller.
 *
 * @param {string} streamName  One of the STREAMS values (e.g. 'actions')
 * @param {string} eventType   A label like 'ACTION_CREATED', 'SESSION_CREATED', etc.
 * @param {object} data        The record payload (will be JSON-stringified)
 */
async function logToCloudWatch(streamName, eventType, data) {
  if (!ENABLED) return;

  try {
    await ensureLogGroupAndStreams();

    const cw = getClient();
    const sequenceToken = await getSequenceToken(streamName);

    const message = JSON.stringify({
      eventType,
      timestamp: new Date().toISOString(),
      ...data
    });

    const params = {
      logGroupName: LOG_GROUP,
      logStreamName: streamName,
      logEvents: [
        {
          timestamp: Date.now(),
          message
        }
      ]
    };

    if (sequenceToken) {
      params.sequenceToken = sequenceToken;
    }

    const res = await cw.send(new PutLogEventsCommand(params));
    sequenceTokens[streamName] = res.nextSequenceToken;
  } catch (err) {
    // Never let CloudWatch failures break the app
    console.error(`[CloudWatch] Failed to log ${eventType} to ${streamName}:`, err.message);
  }
}

// Convenience helpers for each record type
const cwLog = {
  action: (data) => logToCloudWatch(STREAMS.actions, 'ACTION_CREATED', data),
  session: (data) => logToCloudWatch(STREAMS.sessions, 'SESSION_CREATED', data),
  prompt: (data) => logToCloudWatch(STREAMS.prompts, 'PROMPT_CREATED', data),
  user: (data) => logToCloudWatch(STREAMS.users, 'USER_CREATED', data),
  credential: (data) => logToCloudWatch(STREAMS.credentials, 'CREDENTIAL_STORED', data),
  routine: (data) => logToCloudWatch(STREAMS.routines, 'ROUTINE_CREATED', data),
  connection: (data) => logToCloudWatch(STREAMS.connections, 'CONNECTION_UPSERTED', data)
};

module.exports = { logToCloudWatch, cwLog, STREAMS };
