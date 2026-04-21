'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { Route } from 'next';
import { SearchInput } from './SearchInput';

export type ListSearchInputProps = {
  param?: string;
  placeholder?: string;
  debounceMs?: number;
};

export function ListSearchInput({
  param = 'q',
  placeholder = '검색',
  debounceMs = 300,
}: ListSearchInputProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const paramValue = searchParams.get(param) ?? '';
  const [value, setValue] = useState<string>(paramValue);

  // URL 외부 네비게이션(뒤로가기 등)으로 searchParams가 변하면 input도 sync.
  useEffect(() => {
    setValue(paramValue);
  }, [paramValue]);

  useEffect(() => {
    const t = setTimeout(() => {
      const params = new URLSearchParams(
        Array.from(searchParams.entries()),
      );
      const trimmed = value.trim();
      if (trimmed) params.set(param, trimmed);
      else params.delete(param);
      const qs = params.toString();
      const next = (qs ? `${pathname}?${qs}` : pathname) as Route;
      router.replace(next);
    }, debounceMs);
    return () => clearTimeout(t);
    // searchParams·router·pathname은 컴포넌트 lifetime 동안 사실상 안정.
    // 의존성 추가 시 매 렌더마다 replace 실행돼 무한 루프 위험.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <SearchInput
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onClear={() => setValue('')}
      placeholder={placeholder}
    />
  );
}
