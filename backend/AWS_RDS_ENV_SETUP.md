# AWS RDS .env Configuration Guide

Based on your connection code, here's what you need in your `backend/.env` file.

---

## ✅ Correct .env Format

Your `.env` file should look like this (remove any `export` statements - that's shell syntax, not .env syntax):

```bash
# AWS RDS Connection Parameters
DB_HOST=database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_master_password_here
DB_NAME=agenttrust

# SSL Certificate Path (if using certificate file)
# Option 1: With certificate file
DB_SSL_CERT_PATH=/certs/global-bundle.pem

# Option 2: Without certificate file (simpler, uses rejectUnauthorized: false)
# Just leave DB_SSL_CERT_PATH empty or don't include it

# Full connection string (alternative to individual params above)
# DATABASE_URL=postgresql://postgres:your_password@database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com:5432/agenttrust?sslmode=require
```

---

## 🔧 Two Options for SSL

### Option 1: With Certificate File (More Secure)

If you have the certificate file at `/certs/global-bundle.pem`:

```bash
DB_HOST=database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=agenttrust
DB_SSL_CERT_PATH=/certs/global-bundle.pem
```

**Note**: Make sure the certificate file exists at that path. If you're on Windows, the path might be different (e.g., `C:\certs\global-bundle.pem`).

### Option 2: Without Certificate File (Simpler)

If you're using `rejectUnauthorized: false` (which your code shows), you don't need the certificate file:

```bash
DB_HOST=database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=agenttrust
# Don't include DB_SSL_CERT_PATH - SSL will use rejectUnauthorized: false
```

---

## 📝 Complete .env Example

Here's a complete `.env` file with all required variables:

```bash
# ============================================
# AWS RDS PostgreSQL Configuration
# ============================================
DB_HOST=database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_master_password_here
DB_NAME=agenttrust

# SSL Configuration (optional)
# If you have the certificate file:
# DB_SSL_CERT_PATH=/certs/global-bundle.pem
# If not, leave this out and SSL will use rejectUnauthorized: false

# Alternative: Use connection string instead of individual params
# DATABASE_URL=postgresql://postgres:your_password@database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com:5432/agenttrust?sslmode=require

# ============================================
# Auth0 Configuration
# ============================================
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_AUDIENCE=https://agenttrust.api
JWKS_URI=https://your-tenant.us.auth0.com/.well-known/jwks.json

# ============================================
# Server Configuration
# ============================================
PORT=3000
NODE_ENV=development

# ============================================
# Security
# ============================================
JWT_ALGORITHM=RS256
RATE_LIMIT_WINDOW_MS=900000
RATE_LIMIT_MAX_REQUESTS=100
CORS_ORIGIN=http://localhost:3000
```

---

## 🚫 Common Mistakes

### ❌ Wrong (Shell Export Syntax)
```bash
DATABASE_URL = export RDSHOST="database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com"
```

### ✅ Correct (.env Format)
```bash
DB_HOST=database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com
```

**Rules for .env files**:
- No `export` keyword
- No spaces around `=`
- No quotes needed (unless value contains spaces)
- One variable per line

---

## 🔍 How to Get Your Certificate File

If you want to use the certificate file approach:

1. **Download AWS RDS Certificate Bundle**:
   - Go to: https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
   - Or: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html

2. **Save it locally**:
   ```bash
   # On Windows, save to: C:\certs\global-bundle.pem
   # On Linux/Mac, save to: /certs/global-bundle.pem
   ```

3. **Update .env**:
   ```bash
   DB_SSL_CERT_PATH=C:\certs\global-bundle.pem  # Windows
   # or
   DB_SSL_CERT_PATH=/certs/global-bundle.pem     # Linux/Mac
   ```

---

## ✅ Testing Your Configuration

After updating your `.env` file:

1. **Test database connection**:
   ```bash
   cd backend
   npm run create-db
   ```

2. **Run migrations**:
   ```bash
   npm run migrate
   ```

3. **Start server**:
   ```bash
   npm start
   ```

---

## 🎯 Quick Fix for Your Current .env

Replace this line:
```bash
DATABASE_URL = export RDSHOST="database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com"
```

With:
```bash
DB_HOST=database-1.cns4w0k244eh.us-east-2.rds.amazonaws.com
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_actual_password_here
DB_NAME=agenttrust
```

That's it! The migration script will automatically use SSL with `rejectUnauthorized: false` for AWS RDS connections.
