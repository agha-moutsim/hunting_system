import SellerPanel from "@/components/SellerPanel";

/**
 * PHASE H - one seller's stored footprint.
 *
 * The page is a server shell so the dynamic username and optional query are
 * read with this Next.js version's Promise-based `params` and `searchParams`.
 * The panel itself is a client component because it fetches the read-only API
 * after the page opens; the API spends no Browse call.
 */
export default async function SellerPage({
  params,
  searchParams,
}: {
  params: Promise<{ username: string }>;
  searchParams: Promise<{ query?: string | string[] }>;
}) {
  const { username } = await params;
  const search = await searchParams;
  const query = Array.isArray(search.query)
    ? search.query[0] || ""
    : search.query || "";

  return <SellerPanel username={username} query={query} />;
}
