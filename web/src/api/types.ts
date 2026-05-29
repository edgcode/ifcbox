// DTOs mirroring api/schemas.py and the route result payload.

export interface Storey {
  index: number
  name: string
  elevation: number
  height: number
}

export interface ModelOut {
  model_id: string
  filename: string
  storey_count: number
  status: string
  storeys: Storey[]
}

export interface ModelSummary {
  model_id: string
  filename: string
  storey_count: number
  status: string
  uploaded_at: string
}

export type FloorStatus = 'unprepared' | 'preparing' | 'ready' | 'error'

export interface Terminal {
  id: string
  xyz: [number, number, number]
}

export interface Space {
  id: string
  name: string
  centroid: [number, number, number]
}

export interface GridMeta {
  origin: [number, number]
  resolution: number
  shape: [number, number]
  pipe_z: number
  site_to_world: number[][]
}

export interface FloorDetail {
  model_id: string
  floor_index: number
  name: string
  status: FloorStatus
  terminals: Terminal[]
  spaces: Space[]
  grid?: GridMeta | null
}

export interface WallAttrs {
  id: string
  ifc_type: string
  thickness_m: number
  wall_type: string
  wall_type_name: string
  fire_rating: string
}

export type Walls = Record<string, WallAttrs>

export interface RoomClass {
  key: string
  label: string
  color: string
}

export type AnchorType = 'point' | 'terminal' | 'room'

export interface AnchorIn {
  type: AnchorType
  id?: string
  xyz?: [number, number, number]
}

export interface RouteParamsIn {
  clearance_weight?: number
  wall_penalty?: number
  bend_penalty?: number
  diameter?: number
  corridor_weight?: number
  strict_doors?: boolean
}

export type RouteMode = 'trunk' | 'independent'

export interface RouteRequest {
  source: AnchorIn
  targets: AnchorIn[]
  mode?: RouteMode
  params?: RouteParamsIn
}

export interface RouteSegment {
  target_id: string | null
  length_m: number
  branch_from: number | null
  waypoints: [number, number, number][]
}

export interface RouteResult {
  route_id: string
  model_id: string
  floor_index: number
  mode: RouteMode
  total_length_m: number
  diameter_m: number
  discipline: string
  segments: RouteSegment[]
  branch_points: [number, number, number][]
  unreachable_targets: string[]
  mesh_url: string
}

export interface RouteSummary {
  route_id: string
  floor_index: number
  mode: RouteMode
  total_length_m: number
  segment_count: number
  created_at: string
}

export interface PrepProgress {
  status: FloorStatus
  stage: string
  pct: number
  error: string
}
