{
    'name': 'Project Custom Milestone',
    'version': '1.0',
    'summary': 'Manage project milestones with payment tracking',
    'category': 'Project',
    'author': 'Your Company',
    'depends': ['project','sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_milestone_views.xml',
    ],
    'installable': True,
    'application': True,
}
