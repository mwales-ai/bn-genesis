#include "GenesisSpriteViewer.h"
#include "ui/sidebar.h"

extern "C"
{
    BN_DECLARE_UI_ABI_VERSION

    BINARYNINJAPLUGIN bool UIPluginInit()
    {
        Sidebar::addSidebarWidgetType(new GenesisSpriteViewerWidgetType());
        return true;
    }
}
