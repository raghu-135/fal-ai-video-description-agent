export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.pathname.slice(1);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    if (request.method === "GET" && url.searchParams.has("list")) {
      const prefix = url.searchParams.get("prefix") || key || "";
      const cursor = url.searchParams.get("cursor") || undefined;
      const requestedLimit = Number(url.searchParams.get("limit") || "1000");
      const limit = Math.max(1, Math.min(Number.isFinite(requestedLimit) ? requestedLimit : 1000, 1000));
      const listed = await env.BUCKET.list({ prefix, cursor, limit });
      const objects = listed.objects.map((object) => ({
        key: object.key,
        size: object.size,
        etag: object.etag,
        httpEtag: object.httpEtag,
        uploaded: object.uploaded ? object.uploaded.toISOString() : null,
      }));

      return jsonResponse({
        prefix,
        truncated: listed.truncated,
        cursor: listed.cursor || null,
        objects,
      });
    }

    if (!key) {
      return new Response("codex-hackathon-public bucket", { status: 200, headers: corsHeaders() });
    }

    if (request.method === "GET" || request.method === "HEAD") {
      const rangeHeader = request.headers.get("range");
      const head = await env.BUCKET.head(key);
      if (!head) {
        return new Response("Not found", { status: 404 });
      }

      let range = null;
      if (rangeHeader) {
        const match = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader);
        if (!match) {
          return new Response("Invalid range", { status: 416 });
        }

        const size = head.size;
        let start = match[1] ? Number(match[1]) : null;
        let end = match[2] ? Number(match[2]) : null;

        if (start === null && end !== null) {
          start = Math.max(size - end, 0);
          end = size - 1;
        } else {
          start = start ?? 0;
          end = Math.min(end ?? size - 1, size - 1);
        }

        if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start || start >= size) {
          return new Response("Range not satisfiable", {
            status: 416,
            headers: { "content-range": `bytes */${size}` },
          });
        }

        range = { offset: start, length: end - start + 1, start, end };
      }

      const object = await env.BUCKET.get(
        key,
        range ? { range: { offset: range.offset, length: range.length } } : undefined,
      );
      if (!object) {
        return new Response("Not found", { status: 404 });
      }

      const headers = new Headers();
      object.writeHttpMetadata(headers);
      headers.set("etag", object.httpEtag);
      applyCors(headers);
      headers.set("accept-ranges", "bytes");

      const status = range ? 206 : 200;
      if (range) {
        headers.set("content-range", `bytes ${range.start}-${range.end}/${head.size}`);
        headers.set("content-length", String(range.length));
      } else {
        headers.set("content-length", String(head.size));
      }

      if (request.method === "HEAD") {
        return new Response(null, { status, headers });
      }
      return new Response(object.body, { status, headers });
    }

    if (request.method === "PUT") {
      await env.BUCKET.put(key, request.body, {
        httpMetadata: { contentType: request.headers.get("content-type") || "application/octet-stream" },
      });
      return new Response("OK", { status: 200, headers: corsHeaders() });
    }

    if (request.method === "DELETE") {
      await env.BUCKET.delete(key);
      return new Response("Deleted", { status: 200, headers: corsHeaders() });
    }

    return new Response("Method not allowed", { status: 405, headers: corsHeaders() });
  },
};

function jsonResponse(data, init = {}) {
  const headers = new Headers(init.headers);
  headers.set("content-type", "application/json");
  applyCors(headers);
  return new Response(JSON.stringify(data, null, 2) + "\n", { ...init, headers });
}

function corsHeaders() {
  const headers = new Headers();
  applyCors(headers);
  return headers;
}

function applyCors(headers) {
  headers.set("access-control-allow-origin", "*");
  headers.set("access-control-allow-methods", "GET,HEAD,PUT,DELETE,OPTIONS");
  headers.set("access-control-allow-headers", "content-type,range");
}
