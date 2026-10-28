import type { ComponentProps, MouseEvent } from "react";

type LinkProps = Omit<ComponentProps<"a">, "href"> & { href: string };

/** Keep ordinary anchor semantics and existing click guards without Next's runtime. */
export default function Link({ href, onClick, ...props }: LinkProps) {
  function navigate(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if ((props.target && props.target !== "_self") || props.download != null) return;
    const destination = new URL(href, window.location.href);
    if (destination.origin !== window.location.origin) return;
    event.preventDefault();
    window.history.pushState(null, "", destination);
    window.dispatchEvent(new PopStateEvent("popstate"));
    if (destination.hash) document.getElementById(destination.hash.slice(1))?.scrollIntoView();
    else window.scrollTo(0, 0);
  }
  return <a {...props} href={href} onClick={navigate} />;
}
