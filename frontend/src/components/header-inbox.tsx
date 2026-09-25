"use client";

import Link from "next/link";
import { useIdentity } from "@/components/identity";
import { useWallet } from "@/hooks/use-wallet";

export function HeaderInbox() {
  const wallet = useWallet();
  const { verified } = useIdentity(wallet.address);
  return verified ? <Link href="/buzon" className="transition-colors hover:text-primary">Buzón</Link> : null;
}
