import { Compass } from "lucide-react";

import { EmptyState } from "@/components/empty-state";

export default function NotFound() {
  return (
    <EmptyState icon={Compass} title="Esta página no existe" testId="pagina-no-encontrada"
      actions={[
        { label: "Ir al inicio", href: "/", primary: true },
        { label: "Crear una tarea", href: "/cliente" },
        { label: "Ver programadores", href: "/programadores" },
      ]}>
      Revisa que el enlace esté completo. Si te invitaron a una tarea, abre el enlace exactamente como te lo compartieron.
    </EmptyState>
  );
}
