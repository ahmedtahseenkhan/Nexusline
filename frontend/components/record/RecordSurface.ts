"use client";

import { createContext, useContext } from "react";

/** Which column of a RecordDrawer a component is rendered in: "main", "aside" (the
 *  rail), or null outside a drawer. RecordApproval reads it to go compact in a rail. */
export type RecordSurface = "main" | "aside";

export const RecordSurfaceContext = createContext<RecordSurface | null>(null);

export function useRecordSurface(): RecordSurface | null {
  return useContext(RecordSurfaceContext);
}
