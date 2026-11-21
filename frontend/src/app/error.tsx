"use client"; // los límites de error son componentes de cliente

import { useEffect } from "react";
import { TriangleAlert } from "lucide-react";

import { EmptyState } from "@/components/empty-state";

export default function ErrorPage({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <EmptyState icon={TriangleAlert} tone="alert" title="Algo falló al mostrar esta página" testId="error-pagina"
      actions={[{ label: "Intentar de nuevo", onClick: retry, primary: true }, { label: "Ir al inicio", href: "/" }]}>
      Tus depósitos y pagos no dependen de esta página: viven en el contrato de Stellar. Vuelve a intentarlo; si sigue
      fallando, recarga el navegador.
    </EmptyState>
  );
}
