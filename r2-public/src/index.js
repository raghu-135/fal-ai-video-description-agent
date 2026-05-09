export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.pathname.slice(1);

    if (!key) {
      return new Response("codex-hackathon-public bucket", { status: 200 });
    }

    if (request.method === "GET" || request.method === "HEAD") {
      const object = await env.BUCKET.get(key);
      if (!object) {
        return new Response("Not found", { status: 404 });
      }

      const headers = new Headers();
      object.writeHttpMetadata(headers);
      headers.set("etag", object.httpEtag);
      headers.set("access-control-allow-origin", "*");

      if (request.method === "HEAD") {
        return new Response(null, { headers });
      }
      return new Response(object.body, { headers });
    }

    if (request.method === "PUT") {
      await env.BUCKET.put(key, request.body, {
        httpMetadata: { contentType: request.headers.get("content-type") || "application/octet-stream" },
      });
      return new Response("OK", { status: 200 });
    }

    if (request.method === "DELETE") {
      await env.BUCKET.delete(key);
      return new Response("Deleted", { status: 200 });
    }

    return new Response("Method not allowed", { status: 405 });
  },
};
