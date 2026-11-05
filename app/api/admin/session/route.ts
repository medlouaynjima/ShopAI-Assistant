import { timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

const cookieName = "shopassist_admin";

export async function GET(request: NextRequest) {
  return NextResponse.json({
    authenticated: Boolean(
      process.env.ADMIN_API_KEY && request.cookies.get(cookieName)?.value,
    ),
  });
}

export async function POST(request: NextRequest) {
  const configuredKey = process.env.ADMIN_API_KEY ?? "";
  if (!configuredKey) {
    return NextResponse.json(
      { detail: "Admin access is disabled until ADMIN_API_KEY is configured." },
      { status: 503 },
    );
  }

  const origin = request.headers.get("origin");
  if (origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  const body = await request.json().catch(() => null) as
    | { action?: string; key?: string }
    | null;
  const response = NextResponse.json({ authenticated: false });
  if (body?.action === "logout") {
    response.cookies.set(cookieName, "", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/api/backend/admin",
      maxAge: 0,
    });
    return response;
  }

  const providedKey = body?.key ?? "";
  const expected = Buffer.from(configuredKey);
  const provided = Buffer.from(providedKey);
  if (expected.length !== provided.length || !timingSafeEqual(expected, provided)) {
    return NextResponse.json({ detail: "Invalid admin key." }, { status: 401 });
  }

  const authenticated = NextResponse.json({ authenticated: true });
  authenticated.cookies.set(cookieName, configuredKey, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/api/backend/admin",
    maxAge: 8 * 60 * 60,
  });
  return authenticated;
}
