// Quick script to get Auth0 token for testing
// Usage: node test/get-token.js

const axios = require('axios');
require('dotenv').config();

async function getToken() {
  try {
    console.log('🔑 Getting Auth0 token...\n');
    
    // Validate environment variables
    if (!process.env.AUTH0_DOMAIN) {
      throw new Error('AUTH0_DOMAIN not set in .env');
    }
    if (!process.env.AUTH0_CLIENT_ID) {
      throw new Error('AUTH0_CLIENT_ID not set in .env');
    }
    if (!process.env.AUTH0_CLIENT_SECRET) {
      throw new Error('AUTH0_CLIENT_SECRET not set in .env');
    }
    if (!process.env.AUTH0_AUDIENCE) {
      throw new Error('AUTH0_AUDIENCE not set in .env');
    }
    
    const response = await axios.post(
      `https://${process.env.AUTH0_DOMAIN}/oauth/token`,
      {
        client_id: process.env.AUTH0_CLIENT_ID,
        client_secret: process.env.AUTH0_CLIENT_SECRET,
        audience: process.env.AUTH0_AUDIENCE,
        grant_type: 'client_credentials'
      }
    );
    
    console.log('✅ Token obtained successfully!\n');
    console.log('Token:', response.data.access_token);
    console.log('Type:', response.data.token_type);
    console.log('Expires in:', response.data.expires_in, 'seconds');
    console.log('\n💡 Copy the token above to use in API requests');
    console.log('Example:');
    console.log(`curl -H "Authorization: Bearer ${response.data.access_token.substring(0, 20)}..." http://localhost:3000/api/actions`);
    
    return response.data.access_token;
  } catch (error) {
    console.error('❌ Failed to get token:', error.message);
    if (error.response) {
      console.error('Response:', error.response.data);
    }
    process.exit(1);
  }
}

getToken();
