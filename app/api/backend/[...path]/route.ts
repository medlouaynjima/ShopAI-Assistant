import { NextRequest, NextResponse } from "next/server";

const apiBase =
  process.env.SHOPASSIST_API_URL ?? "http://127.0.0.1:8002/api/v1";
const allowedRoutes = new Set([
  "auth/register",
  "auth/verify-email",
  "auth/login",
  "auth/me",
  "auth/logout",
  "products",
  "products/categories",
  "orders/mine",
  "orders/checkout",
  "chat",
  "chat/guest",
  "chat/history",
  "admin/dashboard",
  "admin/tickets",
  "admin/returns/pending",
  "admin/audit",
]);

type RouteContext = { params: Promise<{ path: string[] }> };

function isAllowedAdminAction(endpoint: string) {
  return /^admin\/tickets\/[A-Za-z0-9_-]+$/.test(endpoint)
    || /^admin\/returns\/[A-Za-z0-9_-]+\/approve$/.test(endpoint);
}

function isAllowedCancellationConfirmation(endpoint: string) {
  return /^cancellation-requests\/CAN-[A-Za-z0-9-]+\/confirm$/.test(endpoint);
}

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const endpoint = path.join("/");
  if (!allowedRoutes.has(endpoint) && !isAllowedAdminAction(endpoint) && !isAllowedCancellationConfirmation(endpoint)) {
    return NextResponse.json({ detail: "Not found." }, { status: 404 });
  }

  const token = request.cookies.get("shopassist_session")?.value;
  const adminKey = request.cookies.get("shopassist_admin")?.value;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (endpoint.startsWith("admin/")) {
    if (!adminKey) {
      return NextResponse.json({ detail: "Admin sign-in is required." }, { status: 401 });
    }
    headers.set("X-Admin-Key", adminKey);
  }
  if (token) headers.set("authorization", `Bearer ${token}`);

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBase}/${endpoint}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    const response = NextResponse.json(
      { detail: "The ShopAssist API is unavailable. Please try again." },
      { status: 502 },
    );
    if (endpoint === "auth/logout") clearSessionCookie(response);
    return response;
  }

  const responseBody = await upstream.text();
  if (endpoint === "auth/login" && upstream.ok) {
    const session = JSON.parse(responseBody) as {
      access_token: string;
      expires_at: string;
      full_name: string;
    };
    const expiresAt = new Date(session.expires_at);
    const maxAge = Math.max(
      0,
      Math.floor((expiresAt.getTime() - Date.now()) / 1000),
    );
    const response = NextResponse.json(
      {
        full_name: session.full_name,
        expires_at: session.expires_at,
      },
      { status: upstream.status },
    );
    response.cookies.set("shopassist_session", session.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      expires: expiresAt,
      maxAge,
    });
    return response;
  }

  const response = new NextResponse(responseBody || null, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
  if (endpoint === "auth/logout" || upstream.status === 401) {
    clearSessionCookie(response);
  }
  return response;
}

function clearSessionCookie(response: NextResponse) {
  response.cookies.set("shopassist_session", "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
