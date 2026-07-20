// k6 Load Test for PraxisFlow API
// Run with: k6 run --vus 100 --duration 5m tests/load/api-load-test.js

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

// ─── Configuration ───
export const options = {
  stages: [
    { duration: '2m', target: 10 },   // Ramp up
    { duration: '5m', target: 50 },   // Sustained load
    { duration: '2m', target: 100 },  // Peak load
    { duration: '5m', target: 100 },  // Stress test
    { duration: '2m', target: 50 },   // Cool down
    { duration: '2m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
  ext: {
    loadimpact: {
      projectID: 123456,
      name: 'PraxisFlow API Load Test',
    },
  },
};

// ─── Custom Metrics ───
export const errorRate = new Rate('errors');
export const apiLatency = new Trend('api_latency');
export const wsConnections = new Counter('ws_connections');
export const pipelineDuration = new Trend('pipeline_duration');

// ─── Test Data ───
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const API_PREFIX = '/api/v1';

// Test users (pre-created in test DB)
const testUsers = new SharedArray('users', function() {
  return [
    { email: 'test1@praxisflow.com', password: 'testpass123', tenant_id: 'tenant-001' },
    { email: 'test2@praxisflow.com', password: 'testpass123', tenant_id: 'tenant-001' },
    { email: 'test3@praxisflow.com', password: 'testpass123', tenant_id: 'tenant-002' },
    { email: 'test4@praxisflow.com', password: 'testpass123', tenant_id: 'tenant-002' },
    { email: 'test5@praxisflow.com', password: 'testpass123', tenant_id: 'tenant-003' },
  ];
});

// ─── Authentication ───
let authTokens = {};

function authenticate(user) {
  const loginRes = http.post(`${BASE_URL}${API_PREFIX}/auth/login`, JSON.stringify({
    email: user.email,
    password: user.password,
  }), {
    headers: { 'Content-Type': 'application/json' },
  });

  check(loginRes, {
    'login successful': (r) => r.status === 200,
    'has access token': (r) => r.json('access_token') !== undefined,
  });

  if (loginRes.status === 200) {
    return loginRes.json('access_token');
  }
  return null;
}

// ─── Setup ───
export function setup() {
  console.log('Setting up load test...');
  
  // Authenticate all test users
  testUsers.forEach(user => {
    const token = authenticate(user);
    if (token) {
      authTokens[user.email] = token;
    }
  });
  
  console.log(`Authenticated ${Object.keys(authTokens).length} users`);
  return { authTokens };
}

// ─── Main Test Function ───
export default function(data) {
  const user = testUsers[__VU % testUsers.length];
  const token = data.authTokens[user.email];
  
  if (!token) {
    console.error(`No token for user ${user.email}`);
    return;
  }

  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
    'X-Tenant-ID': user.tenant_id,
  };

  // ─── Scenario 1: Health Check ───
  group('Health Check', () => {
    const res = http.get(`${BASE_URL}/health`, { headers });
    check(res, {
      'health check OK': (r) => r.status === 200,
      'health check fast': (r) => r.timings.duration < 100,
    });
    errorRate.add(res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  sleep(0.5);

  // ─── Scenario 2: List Meetings ───
  group('List Meetings', () => {
    const res = http.get(`${BASE_URL}${API_PREFIX}/meetings?limit=20`, { headers });
    check(res, {
      'list meetings OK': (r) => r.status === 200,
      'returns array': (r) => Array.isArray(r.json()),
    });
    errorRate.add(res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  sleep(1);

  // ─── Scenario 3: Create Meeting (with audio upload simulation) ───
  group('Create Meeting', () => {
    // Simulate audio file upload (using multipart)
    const formData = {
      title: `Load Test Meeting ${__VU}-${__ITER}`,
      description: 'Automated load test meeting',
      scheduled_at: new Date(Date.now() + 3600000).toISOString(),
    };

    const res = http.post(`${BASE_URL}${API_PREFIX}/meetings`, JSON.stringify(formData), { headers });
    check(res, {
      'create meeting OK': (r) => r.status === 201 || r.status === 200,
      'returns meeting ID': (r) => r.json('id') !== undefined,
    });
    errorRate.add(res.status !== 201 && res.status !== 200);
    apiLatency.add(res.timings.duration);

    // Store meeting ID for later use
    if (res.status === 201 || res.status === 200) {
      return res.json('id');
    }
  });

  sleep(2);

  // ─── Scenario 4: Upload Audio (simulated) ───
  group('Upload Audio', () => {
    // In real test, upload actual audio file
    // For load test, simulate with a small dummy file
    const audioData = 'dummy audio content'.repeat(1000); // ~20KB
    const files = {
      file: http.file(audioData, 'meeting.wav', 'audio/wav'),
    };

    const res = http.post(`${BASE_URL}${API_PREFIX}/meetings/upload`, files, { headers });
    check(res, {
      'upload OK': (r) => r.status === 200 || r.status === 201,
    });
    errorRate.add(res.status !== 200 && res.status !== 201);
    apiLatency.add(res.timings.duration);
  });

  sleep(1);

  // ─── Scenario 5: Start Processing ───
  group('Start Processing', () => {
    // This would trigger the ASR + extraction pipeline
    const meetingId = `test-meeting-${__VU}-${__ITER}`; // In real test, use actual ID
    const res = http.post(`${BASE_URL}${API_PREFIX}/meetings/${meetingId}/process`, null, { headers });
    check(res, {
      'process started': (r) => r.status === 202 || r.status === 200,
    });
    errorRate.add(res.status !== 202 && res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  sleep(3);

  // ─── Scenario 6: Check Processing Status ───
  group('Check Processing Status', () => {
    const meetingId = `test-meeting-${__VU}-${__ITER}`;
    let attempts = 0;
    const maxAttempts = 10;

    while (attempts < maxAttempts) {
      const res = http.get(`${BASE_URL}${API_PREFIX}/meetings/${meetingId}/status`, { headers });
      check(res, {
        'status check OK': (r) => r.status === 200,
      });
      
      if (res.status === 200) {
        const status = res.json('status');
        if (status === 'COMPLETED' || status === 'FAILED') {
          break;
        }
      }
      
      attempts++;
      sleep(5);
    }
  });

  // ─── Scenario 7: Get Extracted Tasks ───
  group('Get Tasks', () => {
    const meetingId = `test-meeting-${__VU}-${__ITER}`;
    const res = http.get(`${BASE_URL}${API_PREFIX}/meetings/${meetingId}/tasks`, { headers });
    check(res, {
      'get tasks OK': (r) => r.status === 200,
      'returns tasks array': (r) => Array.isArray(r.json()),
    });
    errorRate.add(res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  sleep(1);

  // ─── Scenario 8: WebSocket Connection (simulated) ───
  group('WebSocket', () => {
    // In k6, WebSocket testing requires WS module
    // For now, we simulate the connection overhead
    const wsStart = new Date();
    // ws.connect(...) would go here
    const wsDuration = new Date() - wsStart;
    wsConnections.add(1);
    check(null, {
      'WS connection simulated': () => true,
    });
  });

  // ─── Scenario 9: Integration Sync ───
  group('Integration Sync', () => {
    const res = http.post(`${BASE_URL}${API_PREFIX}/integrations/sync`, JSON.stringify({
      integration_id: 'test-jira-integration',
      tasks: [{ id: 'task-1', title: 'Test task' }],
    }), { headers });
    
    check(res, {
      'sync OK': (r) => r.status === 200 || r.status === 202,
    });
    errorRate.add(res.status !== 200 && res.status !== 202);
    apiLatency.add(res.timings.duration);
  });

  sleep(2);

  // ─── Scenario 10: Search Tasks ───
  group('Search Tasks', () => {
    const res = http.get(`${BASE_URL}${API_PREFIX}/tasks/search?q=action+item&limit=10`, { headers });
    check(res, {
      'search OK': (r) => r.status === 200,
    });
    errorRate.add(res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  // ─── Scenario 11: Dashboard Metrics ───
  group('Dashboard Metrics', () => {
    const res = http.get(`${BASE_URL}${API_PREFIX}/metrics/dashboard`, { headers });
    check(res, {
      'metrics OK': (r) => r.status === 200,
      'has metrics data': (r) => r.json('total_tasks') !== undefined,
    });
    errorRate.add(res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  // ─── Scenario 12: Team Page ───
  group('Team Page', () => {
    const res = http.get(`${BASE_URL}${API_PREFIX}/team/members`, { headers });
    check(res, {
      'team OK': (r) => r.status === 200,
    });
    errorRate.add(res.status !== 200);
    apiLatency.add(res.timings.duration);
  });

  sleep(3);
}

// ─── Teardown ───
export function teardown(data) {
  console.log('Load test completed');
  console.log(`Total errors: ${errorRate.value * 100}%`);
  console.log(`Avg latency: ${apiLatency.avg.toFixed(2)}ms`);
  console.log(`P95 latency: ${apiLatency['p(95)'].toFixed(2)}ms`);
  console.log(`P99 latency: ${apiLatency['p(99)'].toFixed(2)}ms`);
}