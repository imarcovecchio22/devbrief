import Link from "next/link";

export default function NoEncontrado() {
  return (
    <div className="mt-20">
      <h1 className="font-sans text-4xl font-bold tracking-tight">No hay diario para esa fecha</h1>
      <p className="mt-4 text-tenue">
        Puede que ese día no haya corrido el pipeline. Los diarios publicados están en el{" "}
        <Link href="/archivo" className="text-tinta underline underline-offset-4">
          archivo
        </Link>
        .
      </p>
    </div>
  );
}
