// Typed API client. Attaches the shared-secret token (X-App-Token) when set.

import type {
  Apartment,
  FloorDetail,
  ModelOut,
  ModelSummary,
  RoomClass,
  RouteRequest,
  RouteResult,
  RouteSummary,
  Walls,
} from './types'

const TOKEN_KEY = 'ifcbox_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setStoredToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

// Asset URLs are loaded by <img>/useGLTF/useTexture and download links, which
// can't set headers — carry the token as a query param instead.
function withToken(url: string): string {
  const token = getToken()
  return token ? `${url}?token=${encodeURIComponent(token)}` : url
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = getToken()
  if (token) headers.set('X-App-Token', token)
  if (init?.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`/api/v1${path}`, { ...init, headers })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new ApiError(res.status, detail || res.statusText)
  }
  const ct = res.headers.get('content-type') ?? ''
  return (ct.includes('application/json') ? res.json() : undefined) as Promise<T>
}

export const api = {
  listModels: () => req<ModelSummary[]>('/models'),
  getModel: (id: string) => req<ModelOut>(`/models/${id}`),
  uploadModel: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<ModelOut>('/models', { method: 'POST', body: fd })
  },
  deleteModel: (id: string) => req<void>(`/models/${id}`, { method: 'DELETE' }),

  floorDetail: (id: string, n: number) =>
    req<FloorDetail>(`/models/${id}/floors/${n}`),
  prepareFloor: (id: string, n: number) =>
    req<{ status: string }>(`/models/${id}/floors/${n}/prepare`, { method: 'POST' }),
  geometryUrl: (id: string, n: number) =>
    withToken(`/api/v1/models/${id}/floors/${n}/geometry`),
  overlayUrl: (id: string, n: number, kind: 'occupancy' | 'clearance' | 'rooms') =>
    withToken(`/api/v1/models/${id}/floors/${n}/overlays/${kind}`),
  getWalls: (id: string, n: number) => req<Walls>(`/models/${id}/floors/${n}/walls`),
  getApartments: (id: string, n: number) => req<Apartment[]>(`/models/${id}/floors/${n}/apartments`),
  refreshApartments: (id: string, n: number) =>
    req<Apartment[]>(`/models/${id}/floors/${n}/apartments/refresh`, { method: 'POST' }),
  getRoomClasses: () => req<RoomClass[]>('/room-classes'),

  submitRoute: (id: string, n: number, body: RouteRequest) =>
    req<RouteResult>(`/models/${id}/floors/${n}/routes`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listRoutes: (id: string) => req<RouteSummary[]>(`/models/${id}/routes`),
  getRoute: (routeId: string) => req<RouteResult>(`/routes/${routeId}`),
  meshUrl: (routeId: string) => withToken(`/api/v1/routes/${routeId}/mesh`),
}

// Build a WebSocket URL for prep progress, carrying the token as a query param
// (browsers can't set headers on WS).
export function prepWsUrl(id: string, n: number): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = getToken()
  const q = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${proto}://${location.host}/api/v1/models/${id}/floors/${n}/prepare/ws${q}`
}
