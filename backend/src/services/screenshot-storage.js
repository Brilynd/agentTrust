const { S3Client, PutObjectCommand, GetObjectCommand } = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');

let _s3Client = null;

function isS3ScreenshotEnabled() {
  return (process.env.SCREENSHOT_STORAGE || 'db').toLowerCase() === 's3' && !!process.env.AWS_S3_BUCKET;
}

function getS3Client() {
  if (_s3Client) return _s3Client;
  _s3Client = new S3Client({
    region: process.env.AWS_REGION || process.env.AWS_DEFAULT_REGION || 'us-east-1'
  });
  return _s3Client;
}

function decodeScreenshotData(screenshot) {
  if (!screenshot || typeof screenshot !== 'string') {
    throw new Error('Invalid screenshot payload');
  }

  let raw = screenshot.trim();
  let contentType = 'image/png';

  const dataUrlMatch = raw.match(/^data:([^;]+);base64,(.+)$/i);
  if (dataUrlMatch) {
    contentType = dataUrlMatch[1] || contentType;
    raw = dataUrlMatch[2];
  }

  // Remove accidental whitespace/newlines from base64 payloads.
  raw = raw.replace(/\s/g, '');
  const buffer = Buffer.from(raw, 'base64');
  if (!buffer || !buffer.length) {
    throw new Error('Empty screenshot content');
  }

  return { buffer, contentType };
}

function buildS3Key({ agentId, actionId, timestamp }) {
  const prefix = (process.env.SCREENSHOT_S3_PREFIX || 'screenshots').replace(/^\/+|\/+$/g, '');
  const safeAgent = (agentId || 'unknown-agent').replace(/[^a-zA-Z0-9_-]/g, '_');
  const safeAction = (actionId || `action-${Date.now()}`).replace(/[^a-zA-Z0-9_-]/g, '_');
  const safeTs = (timestamp || new Date().toISOString()).replace(/[:.]/g, '-');
  return `${prefix}/${safeAgent}/${safeTs}-${safeAction}.png`;
}

async function uploadScreenshotToS3({ screenshot, agentId, actionId, timestamp }) {
  if (!isS3ScreenshotEnabled()) {
    return { screenshot, screenshotS3Key: null };
  }

  const bucket = process.env.AWS_S3_BUCKET;
  const { buffer, contentType } = decodeScreenshotData(screenshot);
  const key = buildS3Key({ agentId, actionId, timestamp });

  const client = getS3Client();
  await client.send(new PutObjectCommand({
    Bucket: bucket,
    Key: key,
    Body: buffer,
    ContentType: contentType,
    CacheControl: 'private, max-age=300'
  }));

  return { screenshot: null, screenshotS3Key: key };
}

async function getScreenshotResponseValue({ screenshot, screenshotS3Key }) {
  if (screenshot) {
    return screenshot;
  }

  if (!screenshotS3Key) {
    return null;
  }

  if (!isS3ScreenshotEnabled()) {
    // If S3 is disabled but old rows contain keys, return null instead of broken data.
    return null;
  }

  const bucket = process.env.AWS_S3_BUCKET;
  const ttl = parseInt(process.env.SCREENSHOT_S3_URL_TTL_SEC || '900', 10);
  const client = getS3Client();

  return getSignedUrl(client, new GetObjectCommand({
    Bucket: bucket,
    Key: screenshotS3Key
  }), { expiresIn: Number.isFinite(ttl) ? ttl : 900 });
}

module.exports = {
  isS3ScreenshotEnabled,
  uploadScreenshotToS3,
  getScreenshotResponseValue
};
