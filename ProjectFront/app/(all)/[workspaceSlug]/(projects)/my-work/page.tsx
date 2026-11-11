import { useParams } from "react-router";
import { AppHeader } from "@/components/core/app-header";
import { PageHead } from "@/components/core/page-title";
import { ContentWrapper } from "@/components/core/content-wrapper";
import { PersonalTodos } from "@/components/home/personal-todos";

export default function MyWorkPage() {
  const { workspaceSlug } = useParams();
  return (
    <>
      <PageHead title="我的工作" />
      <AppHeader
        header={
          <div className="flex items-center gap-2">
            <h1 className="text-16 font-medium">我的工作</h1>
          </div>
        }
      />
      <ContentWrapper className="p-4 sm:p-6">
        {workspaceSlug && <PersonalTodos workspaceSlug={workspaceSlug} />}
      </ContentWrapper>
    </>
  );
}
