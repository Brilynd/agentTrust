#!/bin/bash

# AgentTrust API Testing Script
# Usage: ./test/test-api.sh [token]

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

API_URL="http://localhost:3000/api"

# Get token from argument or environment
if [ -z "$1" ]; then
    if [ -z "$TOKEN" ]; then
        echo -e "${RED}Error: Token required${NC}"
        echo "Usage: $0 <token>"
        echo "Or set TOKEN environment variable"
        exit 1
    fi
    TOKEN=$TOKEN
else
    TOKEN=$1
fi

echo -e "${YELLOW}Testing AgentTrust API...${NC}\n"

# Test 1: Health Check
echo -e "${GREEN}Test 1: Health Check${NC}"
response=$(curl -s http://localhost:3000/health)
if [ $? -eq 0 ]; then
    echo "✅ Health check passed: $response"
else
    echo -e "${RED}❌ Health check failed${NC}"
    exit 1
fi
echo ""

# Test 2: Token Validation
echo -e "${GREEN}Test 2: Token Validation${NC}"
response=$(curl -s -X POST "$API_URL/auth/validate" \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"$TOKEN\"}")
if echo "$response" | grep -q '"valid":true'; then
    echo "✅ Token validation passed"
    echo "Response: $response"
else
    echo -e "${RED}❌ Token validation failed${NC}"
    echo "Response: $response"
fi
echo ""

# Test 3: Log Low-Risk Action
echo -e "${GREEN}Test 3: Log Low-Risk Action${NC}"
response=$(curl -s -X POST "$API_URL/actions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "click",
    "url": "https://github.com/user/repo",
    "domain": "github.com",
    "target": {
      "tagName": "BUTTON",
      "id": "view-btn",
      "text": "View"
    }
  }')
if echo "$response" | grep -q '"success":true'; then
    echo "✅ Low-risk action logged"
    echo "Response: $response"
else
    echo -e "${RED}❌ Failed to log action${NC}"
    echo "Response: $response"
fi
echo ""

# Test 4: Log High-Risk Action (should require step-up)
echo -e "${GREEN}Test 4: Log High-Risk Action (should require step-up)${NC}"
response=$(curl -s -X POST "$API_URL/actions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "click",
    "url": "https://github.com/user/repo",
    "domain": "github.com",
    "target": {
      "tagName": "BUTTON",
      "text": "Delete Repository"
    }
  }')
if echo "$response" | grep -q '"requiresStepUp":true'; then
    echo "✅ High-risk action correctly requires step-up"
    echo "Response: $response"
else
    echo -e "${YELLOW}⚠️  Step-up not required (check policy configuration)${NC}"
    echo "Response: $response"
fi
echo ""

# Test 5: Query Audit Log
echo -e "${GREEN}Test 5: Query Audit Log${NC}"
response=$(curl -s -X GET "$API_URL/actions?limit=5" \
  -H "Authorization: Bearer $TOKEN")
if echo "$response" | grep -q '"success":true'; then
    echo "✅ Audit log query successful"
    echo "Response: $response"
else
    echo -e "${RED}❌ Failed to query audit log${NC}"
    echo "Response: $response"
fi
echo ""

# Test 6: Get Policies
echo -e "${GREEN}Test 6: Get Policies${NC}"
response=$(curl -s -X GET "$API_URL/policies" \
  -H "Authorization: Bearer $TOKEN")
if echo "$response" | grep -q '"success":true'; then
    echo "✅ Policies retrieved"
    echo "Response: $response"
else
    echo -e "${RED}❌ Failed to get policies${NC}"
    echo "Response: $response"
fi
echo ""

echo -e "${GREEN}✅ All tests completed!${NC}"
