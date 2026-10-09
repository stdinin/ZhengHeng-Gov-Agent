import http from 'k6/http'
import { check, sleep } from 'k6'

const baseUrl = __ENV.BASE_URL ?? 'http://localhost:8000/api/v1'
const token = __ENV.ACCESS_TOKEN

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-vus',
      vus: Number(__ENV.VUS ?? 10),
      duration: __ENV.DURATION ?? '5m',
    },
  },
}

export default function chat() {
  if (!token) {
    throw new Error('ACCESS_TOKEN is required; do not place it in the script or repository.')
  }
  const response = http.post(
    `${baseUrl}/chat`,
    JSON.stringify({ query: '请说明政策办理条件。' }),
    { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } },
  )
  check(response, { 'chat returns an explicit result': (reply) => [200, 503].includes(reply.status) })
  sleep(1)
}
