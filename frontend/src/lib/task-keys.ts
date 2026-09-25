// Qué llaves de localStorage son de tareas. Lógica pura, probada en tests/.
//
// Solo cumpleycobra:cliente:* (tokens de cada tarea y la lista) y cumpleycobra:programador:*
// (token de programador). No toca las llaves de la sesión de Pollar ni cumpleycobra:direccion:*.

export const STORAGE_PREFIX = "cumpleycobra";
const TASK_KEY = new RegExp(`^${STORAGE_PREFIX}:(cliente|programador):`);

export function taskStorageKeys(allKeys: string[]): string[] {
  return allKeys.filter((key) => TASK_KEY.test(key));
}
