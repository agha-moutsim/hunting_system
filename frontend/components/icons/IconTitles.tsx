import { SVGProps } from "react";

export default function IconTitles(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      {...props}
    >
      <path d="M4 4h16v3H4V4Zm0 6h16v2H4v-2Zm0 4h11v2H4v-2Zm0 4h14v2H4v-2Z" />
    </svg>
  );
}
